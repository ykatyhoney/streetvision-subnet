import gc

import bittensor as bt
import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoTokenizer, Blip2ForConditionalGeneration, Blip2Processor
from transformers import logging as transformers_logging
from transformers import pipeline

from natix.validator.config import HUGGINGFACE_CACHE_DIR


class PromptGenerator:
    """
    A class for generating and moderating image annotations using transformer models.

    This class provides functionality to generate descriptive captions for images
    using BLIP2 models and optionally moderate the generated text using a separate
    language model.
    """

    def __init__(
        self,
        vlm_name: str,
        llm_name: str,
        device: str = 'cuda' if torch.cuda.is_available() else 'cpu',
    ) -> None:
        """
        Initialize the ImageAnnotationGenerator with specific models and device settings.

        Args:
            model_name: The name of the BLIP model for generating image captions.
            text_moderation_model_name: The name of the model used for moderating
                text descriptions.
            device: The device to use.
            apply_moderation: Flag to determine whether text moderation should be
                applied to captions.
        """
        self.vlm_name = vlm_name
        self.llm_name = llm_name
        self.vlm_processor = None
        self.vlm = None
        self.llm_pipeline = None
        self.device = device

    def are_models_loaded(self) -> bool:
        return (self.vlm is not None) and (self.llm_pipeline is not None)

    def load_models(self) -> None:
        """
        Load the necessary models for image annotation and text moderation onto
        the specified device.
        """
        if self.are_models_loaded():
            bt.logging.warning("Models already loaded")
            return

        bt.logging.info(f"Loading caption generation model {self.vlm_name}")
        self.vlm_processor = Blip2Processor.from_pretrained(self.vlm_name, cache_dir=HUGGINGFACE_CACHE_DIR)
        self.vlm = Blip2ForConditionalGeneration.from_pretrained(
            self.vlm_name, 
            torch_dtype=torch.float32,
            cache_dir=HUGGINGFACE_CACHE_DIR
        )
        self.vlm.to(self.device)
        
        # Convert all float32 parameters to float16 to save memory
        for param in self.vlm.parameters():
            if param.dtype == torch.float32:
                param.data = param.data.to(torch.float16)
        
        # Enable CPU offloading for memory efficiency
        if hasattr(self.vlm, 'enable_model_cpu_offload'):
            self.vlm.enable_model_cpu_offload()
        bt.logging.info(f"Loaded image annotation model {self.vlm_name}")

        bt.logging.info(f"Loading caption moderation model {self.llm_name}")
        llm = AutoModelForCausalLM.from_pretrained(self.llm_name, torch_dtype=torch.bfloat16, cache_dir=HUGGINGFACE_CACHE_DIR)
        tokenizer = AutoTokenizer.from_pretrained(self.llm_name, cache_dir=HUGGINGFACE_CACHE_DIR)
        llm = llm.to(self.device)
        
        # Convert any float32 parameters to float16 for memory efficiency
        for param in llm.parameters():
            if param.dtype == torch.float32:
                param.data = param.data.to(torch.float16)
                
        self.llm_pipeline = pipeline("text-generation", model=llm, tokenizer=tokenizer)
        bt.logging.info(f"Loaded caption moderation model {self.llm_name}")

    def clear_gpu(self) -> None:
        """
        Clear GPU memory by moving models back to CPU and deleting them,
        followed by collecting garbage.
        """
        bt.logging.info("Clearing GPU memory after prompt generation")
        if self.vlm:
            self.vlm.to("cpu")
            del self.vlm
            self.vlm = None

        if self.vlm_processor:
            del self.vlm_processor
            self.vlm_processor = None

        if self.llm_pipeline:
            self.llm_pipeline.model.to("cpu")
            del self.llm_pipeline
            self.llm_pipeline = None

        # Multiple rounds of garbage collection and cache clearing
        for _ in range(3):
            gc.collect()
            torch.cuda.empty_cache()
        
        bt.logging.info("GPU memory cleared")

    def generate(
        self,
        image: Image.Image,
        label: int = None,
        max_new_tokens: int = 60,
        verbose: bool = False,
    ) -> str:
        if not verbose:
            transformers_logging.set_verbosity_error()

        inputs = self.vlm_processor(images=image, text="", return_tensors="pt").to(self.device)
        generated_ids = self.vlm.generate(**inputs, max_new_tokens=max_new_tokens)
        caption = self.vlm_processor.batch_decode(generated_ids, skip_special_tokens=True)[0].strip()

        if not verbose:
            transformers_logging.set_verbosity_info()

        if not caption:
            caption = "Dashcam view of road scene."

        moderated_description = self.moderate(caption, label, max_new_tokens=60)
        return moderated_description

    def moderate(
        self,
        description: str,
        label: int = None,
        max_new_tokens: int = 60,
    ) -> str:
        if label == 1:
            system_content = (
                "[INST]Write a SINGLE sentence under 40 words. "
                "Start with 'Photorealistic dashcam footage of active roadwork with orange traffic cones, "
                "construction barriers, and workers in safety vests'. "
                "Describe the road scene clearly. No paragraphs, no filler text.[/INST]"
            )

        elif label == 0:
            system_content = (
                "[INST]Write a SINGLE sentence under 40 words. "
                "Start with 'Photorealistic dashcam footage of'. "
                "Describe a normal road scene with clear traffic and no construction. "
                "Focus on road type, traffic, weather. No paragraphs, no filler text.[/INST]"
            )

        else:
            system_content = (
                "[INST]Write a SINGLE sentence under 40 words. "
                "Start with 'Photorealistic dashcam footage of'. "
                "Describe the road scene. No paragraphs, no filler text.[/INST]"
            )

        messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": description},
        ]

        try:
            moderated_text = self.llm_pipeline(
                messages,
                max_new_tokens=max_new_tokens,
                pad_token_id=self.llm_pipeline.tokenizer.eos_token_id,
                return_full_text=False,
            )[0]["generated_text"]

            moderated_text = moderated_text.strip()

            if label == 1:
                required_tokens = [
                    "orange traffic cones",
                    "construction barriers",
                    "workers in safety vests",
                ]

                for token in required_tokens:
                    if token not in moderated_text:
                        moderated_text += f", {token}"

            # Ensure single sentence
            moderated_text = moderated_text.split(".")[0] + "."

            # Enforce SDXL 77 token CLIP limit
            moderated_text = self._enforce_clip_token_limit(moderated_text)

            return moderated_text

        except Exception as e:
            bt.logging.error(f"Moderation error: {e}", exc_info=True)
            return description

    def _enforce_clip_token_limit(self, prompt: str, max_tokens: int = 77) -> str:
        try:
            tokenizer = self.llm_pipeline.tokenizer
            tokens = tokenizer(prompt, truncation=False)["input_ids"]

            if len(tokens) <= max_tokens:
                return prompt

            truncated_tokens = tokens[:max_tokens]
            truncated_prompt = tokenizer.decode(truncated_tokens, skip_special_tokens=True)

            # Ensure clean ending
            truncated_prompt = truncated_prompt.rsplit(",", 1)[0].rstrip()
            if not truncated_prompt.endswith("."):
                truncated_prompt += "."

            return truncated_prompt

        except Exception as e:
            bt.logging.warning(f"Token limit enforcement failed: {e}")
            return prompt
