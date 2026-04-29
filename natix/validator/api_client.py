import time


def build_auth_headers(wallet) -> dict:
    timestamp = str(int(time.time()))
    signature = wallet.hotkey.sign(timestamp.encode()).hex()
    return {
        "x-hotkey": wallet.hotkey.ss58_address,
        "x-signature": signature,
        "x-timestamp": timestamp,
    }
