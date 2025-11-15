"""
sitecustomize.py - Auto-imported by Python on startup

This ensures custom tokenizers are registered in ALL Python processes,
including vLLM's multiprocessing subprocesses which use spawn mode.
"""

import sys

# Register chatterbox-vllm custom tokenizers (EnTokenizer, MtlTokenizer)
# We do this manually instead of importing chatterbox_vllm.models.t3 to avoid
# any import errors from missing dependencies (since we installed with --no-deps)
try:
    from vllm import ModelRegistry
    from vllm.transformers_utils.tokenizer_base import TokenizerRegistry

    # Register custom tokenizers exactly as chatterbox-vllm does in __init__.py
    TokenizerRegistry.register("EnTokenizer", "chatterbox_vllm.models.t3.entokenizer", "EnTokenizer")
    TokenizerRegistry.register("MtlTokenizer", "chatterbox_vllm.models.t3.mtltokenizer", "MTLTokenizer")

    # Also register the model
    try:
        from chatterbox_vllm.models.t3.t3 import T3VllmModel
        ModelRegistry.register_model("ChatterboxT3", T3VllmModel)
    except ImportError:
        pass  # Model registration can fail, tokenizer registration is critical

    sys.stderr.write("✅ Chatterbox tokenizers registered via sitecustomize.py\n")
    sys.stderr.flush()
except Exception as e:
    sys.stderr.write(f"⚠️  Failed to register tokenizers: {e}\n")
    sys.stderr.flush()
