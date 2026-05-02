import re
import time
from typing import List

import bittensor as bt
import numpy as np
from httpx import Client, HTTPStatusError, ReadTimeout, Timeout

from natix.constants import TARGET_IMAGE_SIZE
from natix.protocol import prepare_synapse
from natix.utils.image_transforms import apply_augmentation_by_level
from natix.utils.wandb_utils import log_to_wandb
from natix.validator.challenge import determine_challenge_type, fetch_api_challenge
from natix.validator.reward import get_rewards
from natix.validator.utils import fix_ip_format


def statistics_assign_task(self, miner_uid_list, type: int, label: int, payload_ref: str):
    """Report a task assignment to the statistics API. Moved to api_client.py in Step 8."""
    try:
        payload = {
            "validator_uid": int(self.uid),
            "miner_uid_list": [int(uid) for uid in miner_uid_list],
            "type": type,
            "label": int(label),
            "payload_ref": str(payload_ref),
        }
        with Client(timeout=Timeout(30)) as client:
            response = client.post(
                f"{self.config.proxy.proxy_client_url}/organic_tasks/statistics/assign",
                json=payload,
            )
        response.raise_for_status()
        bt.logging.info("Successfully reported task assignment to /statistics/assign")
        return response.json()
    except ReadTimeout:
        bt.logging.warning("Statistics assignment request timed out")
        return None
    except HTTPStatusError as e:
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text
        bt.logging.warning(f"Statistics assignment request failed: {error_detail}")
        return None
    except Exception as e:
        bt.logging.exception(f"Unexpected error while assigning task statistics: {e}")
        return None


def statistics_report_task(self, miner_uid_list: List[int], predictions: List[float], task_id: str):
    """Report task responses to the statistics API. Moved to api_client.py in Step 8."""
    try:
        payload = {
            "validator_uid": int(self.uid),
            "miner_uid_list": [int(uid) for uid in miner_uid_list],
            "predictions": [float(p) for p in predictions],
            "task_id": str(task_id),
        }
        with Client(timeout=Timeout(30)) as client:
            response = client.post(
                f"{self.config.proxy.proxy_client_url}/organic_tasks/statistics/report",
                json=payload,
            )
        response.raise_for_status()
        bt.logging.info("Successfully reported task responses to /statistics/report")
        return response.json()
    except ReadTimeout:
        bt.logging.warning("Statistics report request timed out")
        return None
    except HTTPStatusError as e:
        try:
            error_detail = e.response.json()
        except Exception:
            error_detail = e.response.text
        bt.logging.warning(f"Statistics assignment request failed: {error_detail}")
        return None
    except Exception as e:
        bt.logging.exception(f"Unexpected error while assigning task statistics: {e}")
        return None


async def forward(self):
    challenge_metadata = {}
    label, modality, source_model_task, cache, source = determine_challenge_type(
        self.media_cache, self.synthetic_media_cache
    )
    challenge_metadata.update({"label": label, "modality": modality, "source_model_task": source_model_task, "source": source})

    bt.logging.info(f"Sampling {source} {modality} challenge (label={label})")

    if modality != "image":
        bt.logging.error(f"Unexpected modality: {modality}")
        return
    elif source == "api":
        challenge = await fetch_api_challenge(self, label)
        if challenge is not None:
            label = challenge["label"]
    else:
        challenge = cache.sample(label)

    if challenge is None:
        bt.logging.warning("Challenge unavailable. Skipping.")
        return

    challenge_metadata.update({k: v for k, v in challenge.items() if re.match(r"^(?!image$|video$|videos$|video_\d+$).+", k)})
    input_data = challenge[modality]

    try:
        input_data, level, data_aug_params = apply_augmentation_by_level(input_data, TARGET_IMAGE_SIZE, challenge.get("mask_center"))
    except Exception as e:
        level, data_aug_params = -1, {}
        bt.logging.error(f"Unable to apply augmentations: {e}")

    challenge_metadata["data_aug_params"] = data_aug_params
    challenge_metadata["data_aug_level"] = level

    miner_uids = self.uid_deck.next_k(
        k=self.config.neuron.sample_size,
        metagraph=self.metagraph,
        vpermit_tao_limit=self.config.neuron.vpermit_tao_limit,
        exclude=None,
    )
    axons = [fix_ip_format(self.metagraph.axons[uid]) for uid in miner_uids]
    challenge_metadata["miner_uids"] = miner_uids
    challenge_metadata["miner_hotkeys"] = [axon.hotkey for axon in axons]

    synapse = prepare_synapse(input_data, modality=modality)

    try:
        statistics_response = statistics_assign_task(self, miner_uid_list=miner_uids, type=0, label=int(label), payload_ref=synapse.image)
    except Exception as e:
        bt.logging.error(f"Failed to report task assignment to statistics: {e}")

    bt.logging.info(f"Sending {modality} challenge to {len(miner_uids)} miners")
    start = time.time()
    responses = await self.dendrite(axons=axons, synapse=synapse, deserialize=False, timeout=9)
    predictions = [x.prediction for x in responses]
    bt.logging.debug(f"Predictions of {source} challenge: {predictions}")

    try:
        statistics_report_task(self, miner_uid_list=miner_uids, predictions=predictions, task_id=statistics_response["id"])
    except Exception as e:
        bt.logging.error(f"Failed to report task responses to statistics: {e}")

    bt.logging.info(f"Responses received in {time.time() - start}s")
    bt.logging.success(f"Roadwork {modality} challenge complete!")

    rewards, metrics = get_rewards(
        label=label,
        responses=predictions,
        uids=miner_uids,
        axons=axons,
        performance_trackers=self.performance_trackers,
    )
    self.update_scores(rewards, miner_uids)

    for metric_name in list(metrics[0][modality].keys()):
        challenge_metadata[f"miner_{modality}_{metric_name}"] = [m[modality][metric_name] for m in metrics]

    challenge_metadata.update({"predictions": predictions, "rewards": rewards.tolist(), "scores": list(self.scores)})

    for uid, pred, reward in zip(miner_uids, predictions, rewards):
        if pred != -1:
            bt.logging.success(f"UID: {uid} | Prediction: {pred} | Reward: {reward}")

    if not self.config.wandb.off:
        log_to_wandb(challenge_metadata=challenge_metadata, responses=responses, rewards=rewards, metrics=metrics, scores=self.scores, axons=axons)

    self.save_miner_history()
    if cache is not None:
        cache._prune_extracted_cache()
