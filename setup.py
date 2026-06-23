from pathlib import Path
from setuptools import find_packages, setup

README = Path(__file__).with_name("README.md").read_text(encoding="utf-8")
LICENSE_TEXT = Path(__file__).with_name("LICENSE").read_text(encoding="utf-8")

setup(
    name="niblit",
    version="0.1.0",
    description="NIBLIT-AIOS — Neural Integrated Baseline for Learning, Intelligence, and Tasking",
    long_description=README,
    long_description_content_type="text/markdown",
    license="MIT",
    license_files=["LICENSE"],
    packages=find_packages(),
    include_package_data=True,
)


if __name__ == "__main__":
    print('Running setup.py')
