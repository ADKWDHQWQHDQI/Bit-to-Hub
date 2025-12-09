from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

setup(
    name="bitbucket-github-pr-migration",
    version="1.0.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="Migrate pull requests from Bitbucket to GitHub",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/bitbucket-github-pr-migration",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: Software Development :: Version Control",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    install_requires=[
        "requests>=2.31.0",
        "PyGithub>=2.1.1",
        "PyYAML>=6.0.1",
        "python-dateutil>=2.8.2",
        "tenacity>=8.2.3",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "pr-migrate=main:main",
        ],
    },
    include_package_data=True,
    keywords="bitbucket github migration pull-request pr automation",
)
