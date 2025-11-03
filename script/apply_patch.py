import json
import os
import platform
import re
import resource
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
import docker
from swebench.harness.constants import (
    FAIL_TO_PASS,
    KEY_INSTANCE_ID,
    MAP_REPO_VERSION_TO_SPECS,
    PASS_TO_PASS,
    USE_X86,
    SWEbenchInstance,
)
from swebench.harness.docker_build import build_env_images
from swebench.harness.run_evaluation import get_dataset_from_preds, run_instance
from swebench.harness.test_spec.test_spec import (
    TestSpec,
    make_env_script_list,
    make_repo_script_list,
)
from swebench.harness.test_spec.python import get_test_directives
from swebench.harness.utils import get_modified_files
from tqdm import tqdm
import sys
from pathlib import Path
from datetime import datetime
sys.path.append(str(Path(__file__).resolve().parent))
from settings import settings


START_TEST_OUTPUT = ">>>>> Start Test Output"
END_TEST_OUTPUT = ">>>>> End Test Output"
OPEN_FILE_LIMIT = 4096

NOOP_PATCH = """diff --git a/this_is_invisible_3.py b/this_is_invisible_3.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/this_is_invisible.py
@@ -0,0 +1 @@
+# This is a commented out line
"""

NOOP_PATCH_2 = """diff --git a/this_is_invisible_4.py b/this_is_invisible_4.py
new file mode 100644
index 0000000..e69de29
--- /dev/null
+++ b/this_is_invisible_4.py
@@ -0,0 +1 @@
+# This is a commented out line
"""

LATEST = "latest"
INSTANCE_ID = settings.INSTANCE_ID
DATASET_PATH = Path(__file__).parent / "dataset" / "verified.parquet"
REPRODUCTION_PATH = Path(__file__).parent / "cases" / "reproduction_verified.jsonl"
DATE = "verified_Claude-4-Sonnet_round_c_0"
# DATE = "Qwen3-Coder-Instruct_round_2"

def extract_resolved_info(directory_path):
    # Check if the directory exists
    if not os.path.exists(directory_path) or not os.path.isdir(directory_path):
        return {}

    result = {}
    for subdir in os.listdir(directory_path):
        subdir_path = os.path.join(directory_path, subdir)
        if os.path.isdir(subdir_path):
            report_path = os.path.join(subdir_path, "report.json")
            if os.path.isfile(report_path):
                try:
                    with open(report_path, "r", encoding="utf-8") as report_file:
                        data = json.load(report_file)
                        resolved_value = data.get(subdir, {}).get("resolved", False)
                        result[subdir] = resolved_value
                except (json.JSONDecodeError, KeyError):
                    result[subdir] = False
            # else:
            #     result[subdir] = False
    return result


def make_regression_spec(instance: SWEbenchInstance) -> TestSpec:
    if isinstance(instance, TestSpec):
        return instance
    instance_id = instance[KEY_INSTANCE_ID]
    repo = instance["repo"]
    version = instance["version"]
    base_commit = instance["base_commit"]

    def _from_json_or_obj(key: str) -> Any:
        """If key points to string, load with json"""
        if isinstance(instance[key], str):
            return json.loads(instance[key])
        return instance[key]

    pass_to_pass = _from_json_or_obj(PASS_TO_PASS)
    fail_to_pass = _from_json_or_obj(FAIL_TO_PASS)

    env_name = "testbed"
    repo_directory = f"/{env_name}"
    specs = MAP_REPO_VERSION_TO_SPECS[repo][version]

    repo_script_list = make_repo_script_list(
        specs, repo, repo_directory, base_commit, env_name
    )
    env_script_list = make_env_script_list(instance, specs, env_name)
    if "applied_patch" in instance.keys():
        eval_script_list = make_regression_script_list(
            instance,
            specs,
            env_name,
            repo_directory,
            base_commit,
            instance["applied_patch"],
        )
    else:
        eval_script_list = make_regression_script_list(
            instance, specs, env_name, repo_directory, base_commit
        )
    if platform.machine() in {"aarch64", "arm64"}:
        # use arm64 unless explicitly specified
        arch = "arm64" if instance_id not in USE_X86 else "x86_64"
    else:
        arch = "x86_64"
    if "applied_patch" in instance.keys():
        return TestSpec(
            instance_id=instance_id,
            repo=repo,
            env_script_list=env_script_list,
            repo_script_list=repo_script_list,
            eval_script_list=eval_script_list,
            version=version,
            arch=arch,
            FAIL_TO_PASS=fail_to_pass,  # Remove the fail to pass cases
            PASS_TO_PASS=pass_to_pass,
            language="py",
            docker_specs={
                "pnpm_version": "9.5.0",
                "node_version": "21.6.2",
                "python_version": "3.9",
            },
            namespace="swebench",
        )
    return TestSpec(
        instance_id=instance_id,
        repo=repo,
        env_script_list=env_script_list,
        repo_script_list=repo_script_list,
        eval_script_list=eval_script_list,
        version=version,
        arch=arch,
        FAIL_TO_PASS=fail_to_pass,  # Remove the fail to pass cases
        PASS_TO_PASS=pass_to_pass,
        language="py",
        docker_specs={
            "pnpm_version": "9.5.0",
            "node_version": "21.6.2",
            "python_version": "3.9",
        },
        namespace="swebench",
    )


def make_eval_spec(instance: SWEbenchInstance) -> TestSpec:
    if isinstance(instance, TestSpec):
        return instance
    instance_id = instance[KEY_INSTANCE_ID]
    repo = instance["repo"]
    version = instance["version"]
    base_commit = instance["base_commit"]
    test_patch = instance["test_patch"]

    def _from_json_or_obj(key: str) -> Any:
        """If key points to string, load with json"""
        if isinstance(instance[key], str):
            return json.loads(instance[key])
        return instance[key]

    pass_to_pass = _from_json_or_obj(PASS_TO_PASS)
    fail_to_pass = _from_json_or_obj(FAIL_TO_PASS)

    env_name = "testbed"
    repo_directory = f"/{env_name}"
    specs = MAP_REPO_VERSION_TO_SPECS[repo][version]

    repo_script_list = make_repo_script_list(
        specs, repo, repo_directory, base_commit, env_name
    )
    env_script_list = make_env_script_list(instance, specs, env_name)
    if "applied_patch" in instance.keys():
        eval_script_list = make_eval_script_list(
            instance,
            specs,
            env_name,
            repo_directory,
            base_commit,
            test_patch,
            instance["applied_patch"],
        )
    else:
        eval_script_list = make_eval_script_list(
            instance, specs, env_name, repo_directory, base_commit, test_patch
        )
    if platform.machine() in {"aarch64", "arm64"}:
        # use arm64 unless explicitly specified
        arch = "arm64" if instance_id not in USE_X86 else "x86_64"
    else:
        arch = "x86_64"
    if "applied_patch" in instance.keys():
        return TestSpec(
            instance_id=instance_id,
            repo=repo,
            env_script_list=env_script_list,
            repo_script_list=repo_script_list,
            eval_script_list=eval_script_list,
            version=version,
            arch=arch,
            FAIL_TO_PASS=fail_to_pass,  # Remove the fail to pass cases
            PASS_TO_PASS=pass_to_pass,
            language="py",
            docker_specs={
                "pnpm_version": "9.5.0",
                "node_version": "21.6.2",
                "python_version": "3.9",
            },
            namespace="swebench",
        )
    return TestSpec(
        instance_id=instance_id,
        repo=repo,
        env_script_list=env_script_list,
        repo_script_list=repo_script_list,
        eval_script_list=eval_script_list,
        version=version,
        arch=arch,
        FAIL_TO_PASS=fail_to_pass,  # Remove the fail to pass cases
        PASS_TO_PASS=pass_to_pass,
        language="py",
        docker_specs={
            "pnpm_version": "9.5.0",
            "node_version": "21.6.2",
            "python_version": "3.9",
        },
        namespace="swebench",
    )


def make_eval_script_list(
    instance,
    specs,
    env_name,
    repo_directory,
    base_commit,
    test_patch,
    applied_patch: str = None,
) -> list:
    """
    Applies the test patch and runs the tests.
    """
    HEREDOC_DELIMITER = "EOF_114329324912"
    test_files = get_modified_files(test_patch)
    # Reset test files to the state they should be in before the patch.
    reset_tests_command = f"git checkout {base_commit} {' '.join(test_files)}"
    if applied_patch is not None:
        fake_apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{applied_patch}\n{HEREDOC_DELIMITER}"
    else:
        fake_apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{NOOP_PATCH_2}\n{HEREDOC_DELIMITER}"
    apply_test_patch_command = (
        f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{test_patch}\n{HEREDOC_DELIMITER}"
    )
    test_command = " ".join(
        [
            MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]][
                "test_cmd"
            ],
            *get_test_directives(instance),
        ]
    )
    eval_commands = [
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
        f"cd {repo_directory}",
    ]
    if "eval_commands" in specs:
        eval_commands += specs["eval_commands"]
    eval_commands += [
        f"git config --global --add safe.directory {repo_directory}",  # for nonroot user
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        "git status",
        "git show",
        f"git -c core.fileMode=false diff {base_commit}",
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
    ]
    if "install" in specs:
        eval_commands.append(specs["install"])
    eval_commands += [
        reset_tests_command,
        "git reset --hard",
        fake_apply_test_patch_command,
        apply_test_patch_command,
        f": '{START_TEST_OUTPUT}'",
        test_command,
        f": '{END_TEST_OUTPUT}'",
        reset_tests_command,  # Revert tests after done, leave the repo in the same state as before
    ]
    return eval_commands


def make_regression_script_list(
    instance, specs, env_name, repo_directory, base_commit, applied_patch: str = None
):
    """
    Applies the test patch and runs the tests.
    """
    # Reset test files to the state they should be in before the patch.
    reset_tests_command = f"git checkout {base_commit}"

    HEREDOC_DELIMITER = "EOF_114329324912"
    if applied_patch is not None:
        fake_apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{applied_patch}\n{HEREDOC_DELIMITER}"
    else:
        fake_apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{NOOP_PATCH_2}\n{HEREDOC_DELIMITER}"
    test_command = " ".join(
        [
            MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]][
                "test_cmd"
            ],
            *get_test_directives(instance),
        ]
    )
    eval_commands = [
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
        f"cd {repo_directory}",
    ]
    if "eval_commands" in specs:
        eval_commands += specs["eval_commands"]
    eval_commands += [
        f"git config --global --add safe.directory {repo_directory}",  # for nonroot user
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        "git status",
        "git show",
        f"git diff {base_commit}",
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
    ]
    if "install" in specs:
        eval_commands.append(specs["install"])
    eval_commands += [
        reset_tests_command,
        "git reset --hard",
        fake_apply_test_patch_command,  # If we don't apply some sort of patch the harness won't return the tests which passed
        f": '{START_TEST_OUTPUT}'",
        test_command,
        f": '{END_TEST_OUTPUT}'",
        reset_tests_command,
    ]
    return eval_commands


def run_tests(
    instance_ids: list,
    model_patches: list,
    max_workers: int,
    run_id: str,
    regression_test_file: str,
    instances_to_run: list,
    timeout: int,
    apply_model_patch=True,
    dataset_name="princeton-nlp/SWE-bench_Verified",
    is_eval: bool = False,
):
    assert len(instance_ids) == len(model_patches), (
        "There must be the same number of instance_ids as model patches"
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (OPEN_FILE_LIMIT, OPEN_FILE_LIMIT))

    print(f"Using run_id: {run_id}")

    split = "test"
    client = docker.from_env()
    force_rebuild = False

    predictions = {}

    for idx, one_instance_id in enumerate(instance_ids):
        if not apply_model_patch:
            patch_to_apply = NOOP_PATCH
        else:
            patch_to_apply = model_patches[idx]
        predictions[one_instance_id] = {
            "model_name_or_path": "test",
            "model_patch": patch_to_apply,
            "instance_id": one_instance_id,
        }

    # Use local JSON dataset file instead of HuggingFace Hub
    local_dataset_path = DATASET_PATH
    instances = get_dataset_from_preds(
        local_dataset_path, split, instance_ids, predictions, run_id, False
    )

    print(f"Running {len(instances)} unevaluated instances...")
    if not instances:
        print("No instances to run.")
    else:
        build_env_images(client, instances, force_rebuild, max_workers)

    instance_test_dict = {}

    if regression_test_file:
        with open(regression_test_file, "r") as file:
            for line in file:
                json_obj = json.loads(line.strip())
                instance_id = json_obj["instance_id"]
                test = json_obj["tests_passing_in_original_repo"]
                instance_test_dict[instance_id] = test

    no_f2p_instances = []
    for instance in instances:
        revised_instance = instance
        if apply_model_patch:
            revised_instance["applied_patch"] = predictions[instance["instance_id"]][
                "model_patch"
            ]
        revised_instance["FAIL_TO_PASS"] = "[]"
        # DO NOT USE any of the PASS_TO_PASS in swebench
        # it is either obtained from all passing tests (after LLM filtering)
        # or all tests are ran
        if regression_test_file:
            revised_instance["PASS_TO_PASS"] = instance_test_dict[
                instance["instance_id"]
            ]
        else:
            revised_instance["PASS_TO_PASS"] = "[]"

        no_f2p_instances.append(revised_instance)
    if is_eval:
        test_specs = list(map(make_eval_spec, no_f2p_instances))
    else:
        test_specs = list(map(make_regression_spec, no_f2p_instances))

    test_specs = rearrange_patches(test_specs)

    instance_image_ids = {x.instance_image_key for x in test_specs}
    existing_images = {
        tag
        for i in client.images.list(all=True)
        for tag in i.tags
        if tag in instance_image_ids
    }
    print(f"Found {len(existing_images)} existing instance images. Will reuse them.")

    # Load in previously evaluated results
    resolved_dict = extract_resolved_info(
        os.path.join("root","hy","regresssion_logs", "run_evaluation", run_id, "test")
    )

    if instances_to_run:
        ids = instances_to_run
    else:
        ids = [
            test_spec.instance_id
            for test_spec in test_specs
            if test_spec.instance_id not in list(resolved_dict.keys())
        ]

    results = {}

    # Set the empty instances as not resolving the issue
    for index, patch in enumerate(model_patches):
        if patch == "":
            resolved_dict[instance_ids[index]] = False

    with tqdm(total=len(ids), smoothing=0, colour="MAGENTA") as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a future for running each instance
            futures = {
                executor.submit(
                    run_instance,
                    test_spec,
                    predictions[test_spec.instance_id],
                    False,  # do not remove them.
                    force_rebuild,
                    client,
                    run_id,
                    timeout,
                ): None
                for test_spec in test_specs
                if test_spec.instance_id in ids
            }
            # Wait for each future to complete
            for future in as_completed(futures):
                pbar.update(1)
                result = future.result()
                if result:
                    instance_id = result[0]
                    resolved = result[1][instance_id]["resolved"]
                    resolved_dict[instance_id] = resolved
                try:
                    # Update progress bar, check if instance ran successfully
                    future.result()
                except Exception:
                    traceback.print_exc()
                    results[instance_id] = False  # Or handle the error case as needed
                    resolved_dict[instance_id] = False
                    continue

    print("All instances run.")
    return resolved_dict, test_specs


def run_reproduction_tests(
    instance_ids: list,
    model_patches: list,
    max_workers: int,
    run_id: str,
    instances_to_run: list,
    timeout: int,
    testing_patches: bool,
    instance_to_reproduction_code: dict = None,
    apply_model_patch=True,
    dataset_name="princeton-nlp/SWE-bench_Verified",
):
    assert len(instance_ids) == len(model_patches), (
        "There must be the same number of instance_ids as model patches"
    )
    resource.setrlimit(resource.RLIMIT_NOFILE, (OPEN_FILE_LIMIT, OPEN_FILE_LIMIT))

    print(f"Using run_id: {run_id}")

    split = "test"
    client = docker.from_env()
    force_rebuild = False

    predictions = {}

    for idx, one_instance_id in enumerate(instance_ids):
        if not apply_model_patch:
            patch_to_apply = NOOP_PATCH
        else:
            patch_to_apply = model_patches[idx]
        if not testing_patches:
            predictions[one_instance_id] = {
                "model_name_or_path": "test",
                "model_patch": NOOP_PATCH_2,
                "instance_id": one_instance_id,
            }
            # instance_to_reproduction_code[one_instance_id] = patch_to_apply
        else:
            predictions[one_instance_id] = {
                "model_name_or_path": "test",  # TODO change.
                "model_patch": patch_to_apply,
                "instance_id": one_instance_id,
            }

    # Use local JSON dataset file instead of HuggingFace Hub
    local_dataset_path = DATASET_PATH
    instances = get_dataset_from_preds(
        local_dataset_path, split, instance_ids, predictions, run_id, False
    )

    if not instances:
        print("No instances to run.")
    else:
        build_env_images(client, instances, force_rebuild, max_workers)

    no_f2p_instances = []

    for instance in instances:
        revised_instance = instance
        revised_instance["FAIL_TO_PASS"] = "[]"
        revised_instance["PASS_TO_PASS"] = "[]"
        if apply_model_patch:
            revised_instance["applied_patch"] = predictions[
                revised_instance["instance_id"]
            ]["model_patch"]
        if instance["instance_id"] in instance_to_reproduction_code:
            revised_instance["production_test"] = instance_to_reproduction_code[
                instance["instance_id"]
            ]
            # only run if there is production test
            no_f2p_instances.append(revised_instance)

    test_specs = list(map(make_reproduction_sec, no_f2p_instances))

    test_specs = rearrange_patches(test_specs)

    instance_image_ids = {x.instance_image_key for x in test_specs}
    existing_images = {
        tag
        for i in client.images.list(all=True)
        for tag in i.tags
        if tag in instance_image_ids
    }
    print(f"Found {len(existing_images)} existing instance images. Will reuse them.")

    # Load in previously evaluated results
    resolved_dict = extract_resolved_info(
        os.path.join("root","hy","reproduction_logs", "run_evaluation", run_id, "test")
    )

    if instances_to_run:
        ids = instances_to_run
    else:
        ids = [
            test_spec.instance_id
            for test_spec in test_specs
            if test_spec.instance_id not in list(resolved_dict.keys())
        ]

    results = {}

    print(
        f"Running {len([test_spec for test_spec in test_specs if test_spec.instance_id in ids])} unevaluated instances..."
    )

    # Set the empty instances as not resolving the issue
    for index, patch in enumerate(model_patches):
        if patch == "":
            resolved_dict[instance_ids[index]] = False

    with tqdm(total=len(ids), smoothing=0, colour="MAGENTA") as pbar:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Create a future for running each instance
            futures = {
                executor.submit(
                    run_instance,
                    test_spec,
                    predictions[test_spec.instance_id],
                    False,  # do not remove them.
                    force_rebuild,
                    client,
                    run_id,
                    timeout,
                ): None
                for test_spec in test_specs
                if test_spec.instance_id in ids
            }
            # Wait for each future to complete
            for future in as_completed(futures):
                pbar.update(1)
                result = future.result()
                if result:
                    instance_id = result[0]
                    resolved = result[1][instance_id]["resolved"]
                    resolved_dict[instance_id] = resolved
                    # See if the tests ran successfully
                    if testing_patches:
                        expected_output = "Issue reproduced"
                        other_patterns = ["Issue resolved", "Other issues"]
                    else:
                        expected_output = "Issue resolved"
                        other_patterns = ["Issue reproduced", "Other issues"]
                    path_to_log = f"/root/hy/reproduction_logs/run_evaluation/{run_id}/{split}/{instance_id}/test_output.txt"
                    passes_tests = txt_file_contains_string(
                        path_to_log, expected_output, other_patterns=other_patterns
                    )
                    results[instance_id] = passes_tests
                try:
                    # Update progress bar, check if instance ran successfully
                    future.result()
                except Exception:
                    traceback.print_exc()
                    results[instance_id] = False
                    resolved_dict[instance_id] = False
                    continue

    print("All instances run.")
    return results


def rearrange_patches(test_specs):
    """
    rearrange the patches such that slower instance_ids are evaluated first
    this way pipelining will be faster.
    """

    slow_instance_ids = ["sympy__sympy-11870"]

    slow_specs = [
        test_spec
        for test_spec in test_specs
        if test_spec.instance_id in slow_instance_ids
    ]

    if len(slow_specs) != 0:
        print(
            f"rearrange patches such that {[x.instance_id for x in slow_specs]} are evaluated first"
        )
        rearranged_test_specs = slow_specs
        for test_spec in test_specs:
            if test_spec.instance_id not in slow_instance_ids:
                rearranged_test_specs.append(test_spec)
        return rearranged_test_specs
    else:
        return test_specs


def txt_file_contains_string(path_to_txt, expected_output, other_patterns=[]):
    """
    Check if the given text file contains the specified string.
    :param path_to_txt: Path to the text file.
    :param expected_output: The string to search for in the text file.
    :return: True if the string is found in the text file, otherwise False.
    """
    try:
        with open(path_to_txt, "r", encoding="utf-8") as file:
            content = file.read()
            filtered_content = remove_ansi_sequences(content)
            for pattern in other_patterns:
                if pattern in filtered_content:
                    return False
            return expected_output in filtered_content

    except FileNotFoundError:
        pass
    except IOError:
        print(f"An error occurred while reading the file at {path_to_txt}.")

    return False


def remove_ansi_sequences(input_string):
    ansi_escape_pattern = r"\x1b\[\d+m"
    clean_string = re.sub(ansi_escape_pattern, "", input_string)

    return clean_string


def make_reproduction_sec(instance: SWEbenchInstance) -> TestSpec:
    if isinstance(instance, TestSpec):
        return instance
    instance_id = instance[KEY_INSTANCE_ID]
    repo = instance["repo"]
    version = instance["version"]
    base_commit = instance["base_commit"]
    production_test = instance["production_test"]

    def _from_json_or_obj(key: str) -> Any:
        """If key points to string, load with json"""
        if isinstance(instance[key], str):
            return json.loads(instance[key])
        return instance[key]

    pass_to_pass = _from_json_or_obj(PASS_TO_PASS)
    fail_to_pass = _from_json_or_obj(FAIL_TO_PASS)

    env_name = "testbed"
    repo_directory = f"/{env_name}"
    specs = MAP_REPO_VERSION_TO_SPECS[repo][version]

    repo_script_list = make_repo_script_list(
        specs, repo, repo_directory, base_commit, env_name
    )
    env_script_list = make_env_script_list(instance, specs, env_name)
    if "applied_patch" in instance.keys():
        eval_script_list = make_reproduction_script_list(
            instance,
            specs,
            env_name,
            repo_directory,
            base_commit,
            production_test,
            instance["applied_patch"],
        )
    else:
        eval_script_list = make_reproduction_script_list(
            instance, specs, env_name, repo_directory, base_commit, production_test
        )
    if platform.machine() in {"aarch64", "arm64"}:
        # use arm64 unless explicitly specified
        arch = "arm64" if instance_id not in USE_X86 else "x86_64"
    else:
        arch = "x86_64"

    return TestSpec(
        instance_id=instance_id,
        repo=repo,
        env_script_list=env_script_list,
        repo_script_list=repo_script_list,
        eval_script_list=eval_script_list,
        version=version,
        arch=arch,
        FAIL_TO_PASS=fail_to_pass,
        PASS_TO_PASS=pass_to_pass,
        language="py",
        docker_specs={
            "pnpm_version": "9.5.0",
            "node_version": "21.6.2",
            "python_version": "3.9",
        },
        namespace="swebench",
    )


def make_reproduction_script_list(
    instance,
    specs,
    env_name,
    repo_directory,
    base_commit,
    reproduce_patch,
    applied_patch: str = None,
):
    """
    Applies new production tests and run tests
    """
    # Reset test files to the state they should be in before the patch.
    reset_tests_command = f"git checkout {base_commit}"

    HEREDOC_DELIMITER = "EOF_114329324912"
    if applied_patch is not None:
        fake_apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{applied_patch}\n{HEREDOC_DELIMITER}"
    else:
        fake_apply_test_patch_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{NOOP_PATCH_2}\n{HEREDOC_DELIMITER}"

    apply_reproduce_test_command = f"git apply -v - <<'{HEREDOC_DELIMITER}'\n{reproduce_patch}\n{HEREDOC_DELIMITER}"
    reproduce_test_command = "python3 reproduce_bug.py"

    eval_commands = [
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
        f"cd {repo_directory}",
    ]
    if "eval_commands" in specs:
        eval_commands += specs["eval_commands"]
    eval_commands += [
        f"git config --global --add safe.directory {repo_directory}",  # for nonroot user
        f"cd {repo_directory}",
        # This is just informational, so we have a record
        "git status",
        "git show",
        f"git diff {base_commit}",
        "source /opt/miniconda3/bin/activate",
        f"conda activate {env_name}",
    ]
    if "install" in specs:
        eval_commands.append(specs["install"])
    eval_commands += [
        reset_tests_command,
        "git reset --hard",
        fake_apply_test_patch_command,  # If we don't apply some sort of patch the harness won't return the tests which passed
        apply_reproduce_test_command,
        f": '{START_TEST_OUTPUT}'",
        reproduce_test_command,
        f": '{END_TEST_OUTPUT}'",
        # reset_tests_command,
    ]
    return eval_commands


def _code_block_to_patch(code_block: str,
                         filename: str = "reproduce_bug.py") -> str:
    """
    将 Markdown ```python 代码块转换成 git-style 补丁文本，
    方便 run_reproduction_tests 用 `git apply` 加载。
    """
    # 去掉 ```python / ``` fence
    code_block = re.sub(r"^```[a-zA-Z]*\n", "", code_block.strip())
    code_block = re.sub(r"```$", "", code_block.strip())

    header = (
        f"diff --git a/{filename} b/{filename}\n"
        "new file mode 100644\n"
        "index 0000000..e69de29\n"
        "--- /dev/null\n"
        f"+++ b/{filename}\n"
        f"@@ -0,0 +1,{len(code_block.splitlines())} @@\n"
    )
    body = "\n".join(f"+{line}" for line in code_block.splitlines())
    return f"{header}{body}\n"

def _load_reproduction_tests(jsonl_path: Path) -> dict[str, str]:
    mapping: dict[str, str] = {}

    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for raw in fh:
            if not raw.strip():
                continue

            obj = json.loads(raw)
            iid = obj["instance_id"]

            # ---- ① 已提供 unified-diff ----
            if "test_patch" in obj and obj["test_patch"].lstrip().startswith("diff"):
                mapping[iid] = obj["test_patch"]
                continue

            code_block = (
                obj.get("raw_output")
                or obj.get("code_block")
                or obj.get("code")
            )
            if code_block is None:
                raise ValueError(f"{iid} 缺少 test_patch / raw_output 字段，无法生成补丁")

            if isinstance(code_block, list):
                code_block = code_block[0]

            mapping[iid] = _code_block_to_patch(code_block)

    return mapping

def extract_passed_count_django_style(log_text: str) -> int:
    ran_match = re.search(r"Ran (\d+) tests?", log_text)
    ran_total = int(ran_match.group(1)) if ran_match else 0

    failed_detail_match = re.search(r"FAILED\s*\(([^)]+)\)", log_text)
    failed_count = 0
    if failed_detail_match:
        detail_text = failed_detail_match.group(1)
        numbers = [int(n) for n in re.findall(r"\b\d+\b", detail_text)]
        failed_count = sum(numbers)
    return ran_total - failed_count

def run_combined_patches_batch(
    patch_json_dir: str,
    timeout: int = 1200,
    max_workers: int = 8,
):
    """批量运行多个JSON文件的combined patches"""
    patch_root = Path(patch_json_dir)
    
    # 按patch类型组织数据: {patch_type: [(instance_id, patch_text, timestamp), ...]}
    patch_groups = {}
    
    # 收集所有JSON文件的patch信息
    for json_path in sorted(patch_root.glob("*.json")):

        filename = json_path.name
        if not filename.endswith(".json"):
            continue
            
        stem = filename.removesuffix(".json")
        parts = stem.rsplit("_", 2)
        if len(parts) != 3:
            print(f"⚠️ 跳过格式错误文件：{filename}")
            continue
        instance_id = parts[0]
        timestamp = f"{parts[1]}_{parts[2]}"
        # #===  
 
        # start_time = datetime.strptime("2025-08-16_14-14-09", "%Y-%m-%d_%H-%M-%S")
        # try:
        #     file_time = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
        # except ValueError:
        #     print(f"⚠️ 跳过无法解析时间戳文件：{filename}")

        # if file_time < start_time:
        #     continue
        # #===  


        
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            for patch_key, patch_text in data.get("combined_diffs", {}).items():
                if patch_key not in patch_groups:
                    patch_groups[patch_key] = []
                patch_groups[patch_key].append((instance_id, patch_text, timestamp))
        except Exception as e:
            print(f"❌ 读取{filename}失败: {e}")
            continue
    
    # 按patch类型批量运行
    all_results = {}
    for patch_type, instances_data in patch_groups.items():
        # if patch_type not in ("raw_patch","variant_0","variant_1","variant_2"):
        #     continue
        print(f"\n🚀 开始批量运行 patch_type: {patch_type}, 共{len(instances_data)}个实例")
        
        instance_ids = [data[0] for data in instances_data]
        patches = [data[1] for data in instances_data]
        
        # 使用patch_type作为run_id
        run_id = f"{DATE}_{patch_type}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
        
        try:
            res1, res2 = run_tests(
                instance_ids,
                patches,
                max_workers,
                run_id,
                None,
                instance_ids,
                timeout,
                True,
                is_eval=False,
            )
            
            # 处理每个实例的结果
            for i, (instance_id, patch_text, timestamp) in enumerate(instances_data):
                log_dir = Path("/root") / "hy" / "logs" / "run_evaluation" / run_id / "test" / instance_id
                txt = log_dir / "test_output.txt"
                
                passed = 0
                if txt.exists():
                    content = txt.read_text(encoding="utf-8")
                    if instance_id.startswith("django"):
                        passed = extract_passed_count_django_style(content)
                    else:
                        match = re.search(r"(\d+)\s+passed", content)
                        if match:
                            passed = int(match.group(1))
                
                summary = {
                    "instance_id":     instance_id,
                    "patch_type":      patch_type,
                    "patch_timestamp": timestamp,
                    "run_id":          run_id,
                    "passed_count":    passed,
                    "patch":           patch_text
                }
                
                result_txt = Path(f"/root/hy/logs/regression_{DATE}.jsonl")
                result_txt.parent.mkdir(parents=True, exist_ok=True)
                with result_txt.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(summary, ensure_ascii=False) + "\n")
            
            all_results[patch_type] = (res1, res2)
            print(f"✅ 完成 patch_type: {patch_type}")
            
        except Exception as e:
            print(f"❌ 运行 patch_type {patch_type} 失败: {e}")
            all_results[patch_type] = None
    
    return all_results


def run_combined_patches_only(
    instance_id: str,
    patch_json_path,
    timeout: int = 1200,
    max_workers: int = 8,
):
    data = json.loads(Path(patch_json_path).read_text(encoding="utf-8"))

    # 从文件名提取 patch_timestamp
    stem = Path(patch_json_path).stem
    prefix = f"{instance_id}_"
    patch_timestamp = stem[len(prefix):] if stem.startswith(prefix) else stem

    results = {}

    def _run_and_summarize(patch_name: str, patch_text: str):
        run_id = f"{instance_id}_{patch_name}_{patch_timestamp}"
        res1, res2 = run_tests(
            [instance_id],
            [patch_text],
            max_workers,
            run_id,
            None,
            [instance_id],
            timeout,
            True,
            is_eval=False,
        )

        log_dir = Path("/root") / "hy" / "logs" / "run_evaluation" / run_id / "test" / instance_id
        txt = log_dir / "test_output.txt"
        print(txt)

        passed = -1
        if txt.exists():
            content = txt.read_text(encoding="utf-8")
            if instance_id.startswith("django"):
                passed = extract_passed_count_django_style(content)
            else:
                match = re.search(r"(\d+)\s+passed", content)
                if match:
                    passed = int(match.group(1))

        summary = {
            "instance_id":     instance_id,
            "patch_type":      patch_name,
            "patch_timestamp": patch_timestamp,
            "run_id":          run_id,
            "passed_count":    passed,
            "patch":           patch_text
        }

        result_txt = Path("/root/hy/logs/regression_08_16.jsonl")
        result_txt.parent.mkdir(parents=True, exist_ok=True)
        with result_txt.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        print(f"📄 [{patch_name}] summary appended to {result_txt}")
        return res1, res2, passed

    for patch_key, patch_text in data.get("combined_diffs", {}).items():
        results[patch_key] = _run_and_summarize(patch_key, patch_text)

    return results

    



def extract_results_from_existing_logs(base_dir: Path = Path("/root/hy/logs/run_evaluation")):
    result_txt = Path("/root/hy/logs/result.jsonl")
    result_txt.parent.mkdir(parents=True, exist_ok=True)

    for run_dir in sorted(base_dir.iterdir()):
        if not run_dir.is_dir():
            continue

        run_id = run_dir.name
        test_root = run_dir / "test"
        if not test_root.exists():
            continue

        for instance_dir in test_root.iterdir():
            instance_id = instance_dir.name
            if not instance_id.startswith("django"):
                continue

            txt_path = instance_dir / "test_output.txt"
            if not txt_path.exists():
                continue

            try:
                timestamp = "_".join(run_id.split("_")[-2:])
                prefix = instance_id + "_"
                suffix = "_" + timestamp
                if run_id.startswith(prefix) and run_id.endswith(suffix):
                    patch_type = run_id[len(prefix):-len(suffix)]
                else:
                    print(f"⚠️ 跳过格式不符: {run_id}")
                    continue
            except Exception as e:
                print(f"❌ 解析失败: {run_id} - {e}")
                continue

            try:
                content = txt_path.read_text(encoding="utf-8")
                passed = extract_passed_count_django_style(content)
            except Exception as e:
                print(f"⚠️ 无法解析 {txt_path}: {e}")
                passed = -1

            summary = {
                "instance_id":     instance_id,
                "run_id":          run_id,
                "patch_type":      patch_type,
                "patch_timestamp": timestamp,
                "passed_count":    passed,
                "patch":           ""
            }

            with result_txt.open("a", encoding="utf-8") as f:
                f.write(json.dumps(summary, ensure_ascii=False) + "\n")

            print(f"✅ 提取完成: {instance_id} ({run_id}), patch_type={patch_type}, passed={passed}")

def run_single_repro_test(
    instance_id: str,
    model_patch_json = None,
    jsonl_path = "/root/hy/reproduction_tests.jsonl",
    timeout: int = 1200,
    max_workers: int = 8,
    apply_model_patch: bool = True,
):  
    all_tests = _load_reproduction_tests(Path(jsonl_path))
    if instance_id not in all_tests:
        raise ValueError(f"{instance_id} 不在 {jsonl_path} 中")
    instance_to_reproduction_code = {instance_id: all_tests[instance_id]}

    if model_patch_json:
        with open(model_patch_json, "r", encoding="utf-8") as f:
            patch_data = json.load(f)
        model_patches = [patch_data["combined_diffs"]["raw_patch"]]
    else:
        model_patches = [""]          
    run_id = f"{instance_id}_reproduction_{datetime.now():%Y-%m-%d_%H-%M-%S}"
    delete_this_is_invisible_file()
    results = run_reproduction_tests(
        instance_ids                  = [instance_id],
        model_patches                 = model_patches,
        max_workers                   = max_workers,
        run_id                        = run_id,
        instances_to_run              = [instance_id],
        timeout                       = timeout,
        testing_patches               = True,
        instance_to_reproduction_code = instance_to_reproduction_code,
        apply_model_patch             = apply_model_patch,
    )
    print("✅ 测试完成:", results)
    return results

def delete_this_is_invisible_file():
    client = docker.from_env()

    # 获取正在运行的容器列表
    containers = client.containers.list(filters={"status": "running"})
    if not containers:
        print("❌ 当前没有运行中的容器")
        return

    # 默认选第一个运行中的容器
    container = containers[0]
    print(f"✅ 正在操作容器: {container.name} ({container.id[:12]})")

    # 你容器里的代码目录，一般是 /app、/root、/home 等，你可以根据你日志调整
    workdir = "/app"

    # 要删除的文件名
    target_file = "this_is_invisible_2.py"

    # 执行删除命令
    result = container.exec_run(
        f"rm -f {target_file}",
        workdir=workdir,
        user="root"
    )

    if result.exit_code == 0:
        print(f"🧹 成功删除 {target_file}（工作目录：{workdir}）")
    else:
        print(f"⚠️ 删除失败（exit_code={result.exit_code}）：{result.output.decode('utf-8')}")

def run_reproduction_patches_batch(
    patch_json_dir: str,
    jsonl_path="/root/hy/reproduction_verified.jsonl",
    timeout: int = 1200,
    max_workers: int = 8,
):
    """批量运行多个JSON文件的reproduction patches"""
    patch_root = Path(patch_json_dir)
    
    # 加载所有的reproduction tests
    all_tests = _load_reproduction_tests(Path(jsonl_path))
    
    # 按patch类型组织数据: {patch_type: [(instance_id, patch_text, timestamp), ...]}
    patch_groups = {}
    
    # 收集所有JSON文件的patch信息
    for json_path in sorted(patch_root.glob("*.json")):
        filename = json_path.name
        if not filename.endswith(".json"):
            continue
            
        stem = filename.removesuffix(".json")
        parts = stem.rsplit("_", 2)
        if len(parts) != 3:
            print(f"⚠️ 跳过格式错误文件：{filename}")
            continue
            
        instance_id = parts[0]
        timestamp = f"{parts[1]}_{parts[2]}"

        # #===  
        # start_time = datetime.strptime("2025-08-16_14-14-09", "%Y-%m-%d_%H-%M-%S")
        # try:
        #     file_time = datetime.strptime(timestamp, "%Y-%m-%d_%H-%M-%S")
        # except ValueError:
        #     print(f"⚠️ 跳过无法解析时间戳文件：{filename}")

        # if file_time < start_time:
        #     continue
        # #===  
        
        # 检查该instance_id是否有reproduction test
        if instance_id not in all_tests:
            print(f"⚠️ {instance_id} 不在 reproduction tests 中，跳过")
            continue
        
        try:
            data = json.loads(json_path.read_text(encoding="utf-8"))
            for patch_key, patch_text in data.get("combined_diffs", {}).items():
                if patch_key not in patch_groups:
                    patch_groups[patch_key] = []
                patch_groups[patch_key].append((instance_id, patch_text, timestamp))
        except Exception as e:
            print(f"❌ 读取{filename}失败: {e}")
            continue
    
    # 按patch类型批量运行
    all_results = {}
    for patch_type, instances_data in patch_groups.items():
        print(f"\n🚀 开始批量运行 reproduction patch_type: {patch_type}, 共{len(instances_data)}个实例")
        
        instance_ids = [data[0] for data in instances_data]
        patches = [data[1] for data in instances_data]
        
        # 准备instance_to_reproduction_code映射
        instance_to_reproduction_code = {
            instance_id: all_tests[instance_id] 
            for instance_id in instance_ids 
            if instance_id in all_tests
        }
        
        # 使用patch_type作为run_id
        run_id = f"{DATE}_repro_{patch_type}_{datetime.now():%Y-%m-%d_%H-%M-%S}"
        
        try:
            res = run_reproduction_tests(
                instance_ids=instance_ids,
                model_patches=patches,
                max_workers=max_workers,
                run_id=run_id,
                instances_to_run=instance_ids,
                timeout=timeout,
                testing_patches=True,
                instance_to_reproduction_code=instance_to_reproduction_code,
                apply_model_patch=True,
            )
            
            # 处理每个实例的结果
            for i, (instance_id, patch_text, timestamp) in enumerate(instances_data):
                log_dir = Path("/root") / "hy" / "logs" / "run_evaluation" / run_id / "test" / instance_id
                txt = log_dir / "test_output.txt"
                
                passed = 0
                if txt.exists():
                    content = txt.read_text(encoding="utf-8")
                    if "Issue resolved" in content:
                        passed = 1
                
                summary = {
                    "instance_id":     instance_id,
                    "patch_type":      patch_type,
                    "patch_timestamp": timestamp,
                    "run_id":          run_id,
                    "passed_count":    passed,
                    "patch":           patch_text,
                }
                
                result_txt = Path(f"/root/hy/logs/reproduction_{DATE}.jsonl")
                result_txt.parent.mkdir(parents=True, exist_ok=True)
                with result_txt.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(summary, ensure_ascii=False) + "\n")
            
            all_results[patch_type] = res
            print(f"✅ 完成 reproduction patch_type: {patch_type}")
            
        except Exception as e:
            print(f"❌ 运行 reproduction patch_type {patch_type} 失败: {e}")
            all_results[patch_type] = None
    
    return all_results


def run_reproduction_patches_only(
    instance_id: str,
    patch_json_path,
    jsonl_path="/root/hy/reproduction_tests.jsonl",
    timeout: int = 1200,
    max_workers: int = 8,
):
    data = json.loads(Path(patch_json_path).read_text(encoding="utf-8"))
    stem = Path(patch_json_path).stem
    prefix = f"{instance_id}_"
    patch_timestamp = stem[len(prefix):] if stem.startswith(prefix) else stem

    all_tests = _load_reproduction_tests(Path(jsonl_path))
    if instance_id not in all_tests:
        raise ValueError(f"{instance_id} 不在 {jsonl_path} 中")
    instance_to_reproduction_code = {instance_id: all_tests[instance_id]}

    results = {}

    def _run_and_summarize(patch_name: str, patch_text: str):
        run_id = f"{instance_id}_{patch_name}_repro_{patch_timestamp}"
        res = run_reproduction_tests(
            instance_ids                  = [instance_id],
            model_patches                 = [patch_text],
            max_workers                   = max_workers,
            run_id                        = run_id,
            instances_to_run              = [instance_id],
            timeout                       = timeout,
            testing_patches               = True,
            instance_to_reproduction_code = instance_to_reproduction_code,
            apply_model_patch             = True,
        )

        log_dir = Path("/root") / "hy" / "logs" / "run_evaluation" / run_id / "test" / instance_id
        txt = log_dir / "test_output.txt"
        print(txt)

        passed = 0
        if txt.exists():
            content = txt.read_text(encoding="utf-8")
            if "Issue resolved" in content:
                passed = 1

        summary = {
            "instance_id":     instance_id,
            "patch_type":      patch_name,
            "patch_timestamp": patch_timestamp,
            "run_id":          run_id,
            "passed_count":    passed,
            "patch":           patch_text,
        }

        result_txt = Path("/root/hy/logs/reproduction_results_08_16.jsonl")
        result_txt.parent.mkdir(parents=True, exist_ok=True)
        with result_txt.open("a", encoding="utf-8") as f:
            f.write(json.dumps(summary, ensure_ascii=False) + "\n")
        print(f"📄 [{patch_name}] reproduction result appended to {result_txt}")
        return res, passed

    for patch_key, patch_text in data.get("combined_diffs", {}).items():
        results[patch_key] = _run_and_summarize(patch_key, patch_text)

    return results

if __name__ == "__main__":
    from pathlib import Path
    import pandas as pd

    current_dir = Path(__file__).parent
    parquet_path = current_dir / "dataset.parquet"
    df = pd.read_parquet(parquet_path)
    # --------
    # batch
    # def get_golden_patch(id):
    #     result = df.loc[df["instance_id"] == id, "patch"]
    #     golden_patch = result.iloc[0] if not result.empty else None
    #     return golden_patch
    # begin = 0
    # for id in df['instance_id'].values:
    #     if id == "django__django-15320": begin =1
    #     if not begin : continue

    #     golden_patch = get_golden_patch(id)
    #     instance_id, model_patch = [id], [golden_patch]
    #     run_noop_patch = f"{id}_noop_patch"
    #     run_golden_patch = f"{id}_golden_patch"
    #     res3, res4 = run_tests(instance_id, model_patch, 1, run_noop_patch, None, [id], 1200, False,is_eval=True)
    #     print(res3)
    #     res1, res2 = run_tests(instance_id, model_patch, 1, run_golden_patch, None, [id], 1200, True,is_eval=True)
    #     print(res1)

    # ids = [
    #     "matplotlib__matplotlib-18869",
    #     "matplotlib__matplotlib-22711"
    # ]
    # patches= [
    #     "diff --git a/lib/matplotlib/__init__.py b/lib/matplotlib/__init__.py\nindex b657a35cf7..34940637e0 100644\n--- a/lib/matplotlib/__init__.py\n+++ b/lib/matplotlib/__init__.py\n@@ -130,6 +130,7 @@ __bibtex__ = r\"\"\"@Article{Hunter:2007,\n }\"\"\"\n \n \n+\n def __getattr__(name):\n     if name == \"__version__\":\n         import setuptools_scm\n@@ -148,6 +149,17 @@ def __getattr__(name):\n         else:  # Get the version from the _version.py setuptools_scm file.\n             __version__ = _version.version\n         return __version__\n+    elif name == \"version_info\":\n+        version_str = __getattr__(\"__version__\").split(\"+\")[0]  # Remove local version identifiers\n+        parsed = parse_version(version_str)\n+        # Convert to tuple format similar to sys.version_info\n+        try:\n+            release = tuple(int(x) for x in parsed.base_version.split('.'))\n+            # Pad with zeros to ensure at least three components (major, minor, micro)\n+            return release + (0,) * (3 - len(release))\n+        except (ValueError, AttributeError):\n+            # Fallback for unusual version strings\n+            return (0, 0, 0)\n     raise AttributeError(f\"module {__name__!r} has no attribute {name!r}\")\n \n \n",
    #     "diff --git a/lib/matplotlib/widgets.py b/lib/matplotlib/widgets.py\nindex da5b40a5ef..656842f316 100644\n--- a/lib/matplotlib/widgets.py\n+++ b/lib/matplotlib/widgets.py\n@@ -709,6 +709,7 @@ class RangeSlider(SliderBase):\n                 facecolor=track_color\n             )\n             ax.add_patch(self.track)\n+\n             self.poly = ax.axhspan(valinit[0], valinit[1], 0, 1, **kwargs)\n             handleXY_1 = [.5, valinit[0]]\n             handleXY_2 = [.5, valinit[1]]\n@@ -897,19 +898,18 @@ class RangeSlider(SliderBase):\n         _api.check_shape((2,), val=val)\n         val[0] = self._min_in_bounds(val[0])\n         val[1] = self._max_in_bounds(val[1])\n+\n         xy = self.poly.xy\n         if self.orientation == \"vertical\":\n             xy[0] = .25, val[0]\n             xy[1] = .25, val[1]\n             xy[2] = .75, val[1]\n             xy[3] = .75, val[0]\n-            xy[4] = .25, val[0]\n         else:\n             xy[0] = val[0], .25\n             xy[1] = val[0], .75\n             xy[2] = val[1], .75\n             xy[3] = val[1], .25\n-            xy[4] = val[0], .25\n         self.poly.xy = xy\n         self.valtext.set_text(self._format(val))\n         if self.drawon:\n",
    # ]
    # run_id = "raw_patch"
    # res3, res4 = run_tests(ids, patches, 4, run_id, None, ids, 1200, False,is_eval=True)

    # print(res3)
    #===
    
    patch_root = Path(f"/root/hy/merge/langchain/logs/{DATE}")
    
    # 批量处理模式 - 推荐使用
    print("🚀 开始批量处理所有JSON文件...")
    
    # 运行 combined patches 批量处理
    print("\n=== 批量运行 Combined Patches ===")
    try:
        combined_results = run_combined_patches_batch(str(patch_root))
        print(f"✅ Combined patches 批量处理完成，处理了 {len(combined_results)} 种patch类型")
    except Exception as e:
        print(f"❌ Combined patches 批量处理失败: {e}")
    
    # 运行 reproduction patches 批量处理
    print("\n=== 批量运行 Reproduction Patches ===")
    try:
        reproduction_results = run_reproduction_patches_batch(str(patch_root))
        print(f"✅ Reproduction patches 批量处理完成，处理了 {len(reproduction_results)} 种patch类型")
    except Exception as e:
        print(f"❌ Reproduction patches 批量处理失败: {e}")
    
    print("\n🎉 所有批量处理任务完成！")
    
    # 原始单文件处理模式（保留作为备用）
    # for path in sorted(patch_root.glob("*.json")):
    #     filename = path.name
    #     if filename.startswith("astropy"):
    #         continue
    #     if not filename.endswith(".json"):
    #         continue

    #     stem = filename.removesuffix(".json")
    #     parts = stem.rsplit("_", 2)
    #     if len(parts) != 3:
    #         print(f"⚠️ 跳过格式错误文件：{filename}")
    #         continue

    #     instance_id = parts[0]
    #     timestamp = f"{parts[1]}_{parts[2]}"
    #     patch_path = str(path)
    #     print(f"\n🚀 开始运行：{instance_id} ({patch_path})")
    #     try:
    #         run_combined_patches_only(instance_id, patch_path)
    #         run_reproduction_patches_only(instance_id,patch_path)
    #     except Exception as e:
    #         print(f"❌ 错误: {instance_id} - {e}")
    
