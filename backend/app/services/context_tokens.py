from pathlib import Path

from tokenizers import Tokenizer

from app.schemas.model_request_snapshot import ModelRequestMessage

DEFAULT_TOKENIZER_PATH = (
    Path(__file__).resolve().parents[3]
    / "scripts/deepseek_v4_tokenizer/deepseek_v4_tokenizer/tokenizer.json"
)

_BOS = "<\uff5cbegin\u2581of\u2581sentence\uff5c>"
_USER = "<\uff5cUser\uff5c>"
_ASSISTANT = "<\uff5cAssistant\uff5c>"


class ContextTokenizer:
    def __init__(self, tokenizer_path: Path = DEFAULT_TOKENIZER_PATH) -> None:
        self._tokenizer = Tokenizer.from_file(str(tokenizer_path))

    def count_text(self, text: str) -> int:
        return len(self._tokenizer.encode(text, add_special_tokens=False).ids)

    def count_messages(self, messages: list[ModelRequestMessage]) -> int:
        systems: list[str] = []
        users: list[str] = []
        for message in messages:
            if message.role == "system":
                systems.append(message.content)
            elif message.role == "user":
                users.append(_USER + message.content)
            else:
                raise ValueError(f"Unsupported context tokenizer message role: {message.role}")

        # Match the bundled chat template, including the assistant generation prefix.
        serialized = _BOS + "\n\n".join(systems) + "".join(users) + _ASSISTANT
        return self.count_text(serialized)
