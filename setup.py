from setuptools import setup, find_packages
from pkg_resources import parse_requirements
import os

with open(os.path.join("oservices", "version.py")) as f:
    version = f.read().split("=")[1].strip().strip("'").strip('"')

with open("requirements.txt", "r") as f:
    requirements = [str(r) for r in parse_requirements(f.read())]

setup(
    name="oservices",
    version=version,
    packages=find_packages(exclude="tests"),
    author="Openergy team",
    author_email="contact@openergy.fr",
    long_description=open("README.md").read(),
    install_requires=requirements,
    url="https://github.com/openergy/oservices",
    classifiers=[
        "Programming Language :: Python",
        "Development Status :: 5 - Production/Stable",
        "Intended Audience :: Science/Research",
        "Natural Language :: French",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.1",
        "Topic :: Scientific/Engineering :: Physics",
    ],
    package_data={"oservices": ["*.txt"]},
    include_package_data=True
)
