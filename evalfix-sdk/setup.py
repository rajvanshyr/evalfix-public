from setuptools import setup, find_packages

setup(
    name="evalfix-sdk",
    version="0.1.0",
    description="Capture production LLM failures and feed them back to evalfix.",
    long_description=open("README.md").read() if __import__("os").path.exists("README.md") else "",
    long_description_content_type="text/markdown",
    author="evalfix",
    python_requires=">=3.8",
    packages=find_packages(exclude=["tests*"]),
    install_requires=[],  # zero required deps — stdlib only
    extras_require={
        "dev": ["pytest"],
    },
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
