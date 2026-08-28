"""Scoped Hugging Face remote-code loading guards."""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from importlib import import_module
from typing import Any


_TOKENIZER_PATCH_LOCK = threading.RLock()


@contextmanager
def pinned_auto_tokenizer_loading(
    transformers_module: Any,
    *,
    model_name: str,
    revision: str,
    local_files_only: bool,
    trust_remote_code: bool,
) -> Iterator[None]:
    """Force remote model code to load its tokenizer from the same immutable pin.

    Some Jina remote-code revisions instantiate ``AutoTokenizer`` internally
    without forwarding the outer model's ``revision`` or ``local_files_only``
    arguments. The scoped classmethod patch closes that reproducibility and
    offline-mode gap while the model constructor runs, then restores the exact
    original descriptor.
    """

    auto_tokenizer = getattr(transformers_module, "AutoTokenizer", None)
    if auto_tokenizer is None or "from_pretrained" not in vars(auto_tokenizer):
        yield
        return

    with _TOKENIZER_PATCH_LOCK:
        original_descriptor = vars(auto_tokenizer)["from_pretrained"]
        original_loader = auto_tokenizer.from_pretrained
        offline_state: list[tuple[Any, str, object]] = []
        if local_files_only:
            for module_name, attribute in (
                ("transformers.utils.hub", "_is_offline_mode"),
                ("huggingface_hub.constants", "HF_HUB_OFFLINE"),
            ):
                try:
                    target_module = import_module(module_name)
                    original_value = getattr(target_module, attribute)
                except (ImportError, AttributeError):
                    continue
                offline_state.append((target_module, attribute, original_value))
                setattr(target_module, attribute, True)

        def pinned_loader(
            cls: type[Any],
            pretrained_model_name_or_path: object,
            *args: object,
            **kwargs: object,
        ) -> Any:
            if str(pretrained_model_name_or_path) == model_name:
                kwargs["revision"] = revision
                kwargs["local_files_only"] = local_files_only
                kwargs.setdefault("trust_remote_code", trust_remote_code)
            return original_loader(
                pretrained_model_name_or_path,
                *args,
                **kwargs,
            )

        setattr(auto_tokenizer, "from_pretrained", classmethod(pinned_loader))
        try:
            yield
        finally:
            setattr(auto_tokenizer, "from_pretrained", original_descriptor)
            for target_module, attribute, original_value in reversed(offline_state):
                setattr(target_module, attribute, original_value)


__all__ = ["pinned_auto_tokenizer_loading"]
