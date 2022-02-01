import os
import sys

if __name__ == "__main__":
    # get repository name
    repo_name = sys.argv[1]
    arch_specific = sys.argv[2]
    try:
        python_version = sys.argv[3] if sys.argv[3] in ("3.6", "3.7") else None
    except IndexError:
        python_version = None
    version = ""
    path = os.getcwd()
    try:
        with open("./RELEASE.md", "r") as f:
            for line in f.readlines():
                if line.startswith("##"):
                    version = line[2:].strip("#").strip()
                    break
    except:
        raise ValueError("Could not parse version from RELEASE.md")
    if version == '':
        raise ValueError("Could not parse version from RELEASE.md")
    with open("./conda-build/meta.yaml", "r") as f:
        meta = f.read()
    if arch_specific == "true":
        meta = meta.replace("__noarch__", "")
        meta = meta.replace("__build_requirements__", "    - cython\n    - numpy")
    else:
        meta = meta.replace("__noarch__", "  noarch: python")
        meta = meta.replace("__build_requirements__", "")
    meta = meta.replace("__name__", repo_name)
    meta = meta.replace("__version__", version)
    meta = meta.replace("__path__", path)
    if python_version == "3.6":
        meta = meta.replace("python>=3.6,<4.0", "python>=3.6,<3.7")
    elif python_version == "3.7":
        meta = meta.replace("python>=3.6,<4.0", "python>=3.7,<3.8")
    dependencies = ""
    # try:
    with open("./requirements.txt", "r") as f:
        for line in f.readlines():
            line = line.strip()
            if line.startswith("#") or line == "":
                continue
            dependencies += f"    - {line}\n"
    # except FileNotFoundError:
    #     # maybe old version:
    #     if not os.path.isfile('requirements-pip.txt'):
    #         raise
    #     with open('requirements-pip.txt', 'r') as f:
    #         for line in f.readlines():
    #             line = line.strip()
    #             dependencies += f'    - {line}'
    #     if os.path.isfile('requirements-conda.txt'):
    #         with open('requirements-conda.txt', 'r') as f:
    #             for line in f.readlines():
    #                 line = line.strip()
    #                 dependencies += f'    - {line}'
    #     if os.path.isfile('requirements-conda.yml'):
    #         with open('requirements-conda.yml', 'r') as f:
    #             start = False
    #             for line in f.readlines():
    #                 if start:
    #                     line = line.strip()
    #                     if not line.startswith('-'):
    #                         break
    #                     dependencies += f'    {line}\n'
    #                 elif 'dependencies' in line:
    #                     start = True
    #     if os.path.isfile('requirements-openergy.txt'):
    #         with open('requirements-openergy.txt', 'r') as f:
    #             for line in f.readlines():
    #                 line = line.strip()
    #                 dependencies += f'    - {line}'
    if arch_specific == "true" and os.path.isfile('./linux_requirements.txt'):
        with open("./linux_requirements.txt", "r") as f:
            for line in f.readlines():
                line = line.strip()
                if line.startswith("#") or line == "":
                    continue
                dependencies += f"    - {line}\n"
    meta = meta.replace("__dependencies__", dependencies)
    with open("./conda-build/meta.yaml", "w") as f:
        f.write(meta)
    print(meta)
