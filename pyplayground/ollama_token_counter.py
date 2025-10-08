#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""Ollama token counting utility.

This module provides functionality to count tokens for Ollama models using
HuggingFace tokenizers. It supports various model types and provides accurate
token counting for chat completions.
"""

import copy
import os
import sys

from llm_tester.logger import log
from transformers import AutoTokenizer

from .model_mapper import model_mapper

os.environ["TRANSFORMERS_VERBOSITY"] = "error"
cached_chat_templates = {}
tokenizers = {}


def load_ollama_tokenizers(models: list[str]):
    """Load all tokenizers for the given ollama models."""
    # Convert Groq models to Ollama models
    groq_models = model_mapper.filter_models_by_client(models, "groq")

    def groq_to_ollama(m):
        return model_mapper.find_entry_by_model_name(m["ollama_alias"])

    ollama_models = list(map(groq_to_ollama, groq_models))

    ollama_models += model_mapper.filter_models_by_client(models, "ollama")

    for m in ollama_models:
        tokenizer = AutoTokenizer.from_pretrained(m["huggingface_alias"])
        tokenizers[m["model"]] = tokenizer


class OllamaTokenCounter:
    """Token counter for Ollama models using HuggingFace tokenizers."""

    def __init__(self):
        """Initialize the OllamaTokenCounter."""
        pass

    def _get_tokenizer(self, ollama_model: str):
        if ollama_model not in tokenizers:
            log.error(f"Unsupported ollama model {ollama_model}, update the map")
            sys.exit(1)

        return tokenizers[ollama_model]

    def num_tokens_get(self, ollama_model: str, msgs: list[dict]):
        """Calculate the number of tokens in the given messages based on the used model."""
        tokenizer = self._get_tokenizer(ollama_model)

        # As we might modify the messages, a deep copy is needed to prevent modification
        # to be visible outside of this function.
        msgs = copy.deepcopy(msgs)

        # If the first message is from the assistant, add an empty user message.
        # The chat_template expects alternating user and assistant messages.
        if msgs[0]["role"] == "assistant":
            msgs = [{"role": "user", "content": ""}] + msgs

        # If the first message is a system message, prepend it to the second message.
        # Some chat templates don't support system messages.
        if msgs[0]["role"] == "system":
            msgs[1]["content"] = msgs[0]["content"] + "\n\n" + msgs[1]["content"]
            msgs.pop(0)

        return len(tokenizer.apply_chat_template(msgs))
