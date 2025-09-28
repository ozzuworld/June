# June/services/june-stt/shared/setup.py
from setuptools import setup, find_packages

setup(
    name="june-stt-shared",
    version="1.0.0",
    description="Shared authentication and utilities for June STT service",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "fastapi>=0.100.0",
        "PyJWT[crypto]>=2.8.0",
        "cryptography>=41.0.0",
        "python-jose[cryptography]>=3.3.0",
    ],
)