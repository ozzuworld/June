from setuptools import setup, find_packages

setup(
    name="june-shared",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.100.0",
        "httpx>=0.24.0", 
        "PyJWT[crypto]>=2.8.0",
        "cryptography>=41.0.0"
    ]
)
