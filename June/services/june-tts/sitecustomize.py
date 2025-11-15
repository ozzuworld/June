"""
sitecustomize.py - Auto-imported by Python on startup

This ensures custom tokenizers are registered in ALL Python processes,
including vLLM's multiprocessing subprocesses which use spawn mode.
"""

# Register chatterbox-vllm custom tokenizers (EnTokenizer, MtlTokenizer)
# This MUST happen before vLLM tries to use them in worker processes
try:
    import chatterbox_vllm.models.t3  # Triggers ModelRegistry and TokenizerRegistry registrations
except ImportError:
    pass  # Package not installed, ignore
