from pathlib import Path

from setuptools import find_packages, setup


ROOT = Path(__file__).parent
README = ROOT / "README.md"


setup(
    name="quiet-droid",
    version="0.7.7",
    description="Minimal terminal coding agent for OpenAI-compatible APIs",
    long_description=README.read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    packages=find_packages(),
    include_package_data=True,
    python_requires=">=3.10",
    entry_points={
        "console_scripts": [
            "qd=quiet_droid.app:main",
            "quiet-droid=quiet_droid.app:main",
        ]
    },
)
