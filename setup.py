from setuptools import setup, find_packages

setup(
    name="evalfix",
    version="0.1.3",
    packages=find_packages(),
    py_modules=["config"],
    install_requires=[
        "flask",
        "flask-sqlalchemy",
        "flask-migrate",
        "anthropic",
        "python-dotenv",
        "click",
        "rich",
        "pyyaml",
    ],
    entry_points={
        "console_scripts": [
            "evalfix=cli.main:cli",
        ],
    },
    python_requires=">=3.11",
)
