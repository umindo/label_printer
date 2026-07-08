from setuptools import setup, find_packages

# setup.py — ERPNext v15 compatibility
# ERPNext v16+ uses pyproject.toml instead, but this file
# ensures the app works on v15 sites as well.

setup(
    name="label_printer",
    version="1.0.0",
    description="Print TSPL item labels from Delivery Note via TSC TDP-225",
    author="Your Company",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=[
        "requests>=2.28",
    ],
    python_requires=">=3.10",
)
