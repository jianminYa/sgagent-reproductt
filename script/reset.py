from pathlib import Path
import pandas as pd
import subprocess
from settings import settings

INSTANCE_ID = settings.INSTANCE_ID
TEST_BED = settings.TEST_BED
PROJECT_NAME = settings.PROJECT_NAME

current_dir = Path(__file__).parent.parent
# parquet_path = current_dir / "dataset.parquet"
parquet_path = current_dir / "dataset" /"lite.parquet"
df = pd.read_parquet(parquet_path)

CONF_PATH = '/root/hy/neo4j-community-5.26.6/conf/neo4j.conf'
def update_database_in_conf(instance_id):
    db_name = instance_id.replace('_', '-')
    print(f"  - 更新 neo4j.conf: initial.dbms.default_database = {db_name}")
    found = False
    new_lines = []
    for line in open(CONF_PATH, 'r'):
        if line.strip().startswith('initial.dbms.default_database='):
            new_lines.append(f'initial.dbms.default_database={db_name}\n')
            found = True
        else:
            new_lines.append(line)
    if not found:
        print("  - initial.dbms.default_database 不存在，追加到文件末尾。")
        new_lines.append(f'initial.dbms.default_database={db_name}\n')
    with open(CONF_PATH, 'w') as f:
        f.writelines(new_lines)

def restart_neo4j():
    print("  - 正在重启 Neo4j ...")
    result = subprocess.run(['neo4j', 'restart'], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"[Error] Neo4j 重启失败，错误码：{result.returncode}")
        print(result.stderr)
    else:
        print("  - Neo4j 重启成功")

def get_base_commit(instance_id):

    result = df.loc[df["instance_id"] == instance_id, "base_commit"]
    return result.iloc[0] if not result.empty else None


def checkout_to_base_commit(instance_id,path):

    base_commit = get_base_commit(instance_id)
    if base_commit is None:
        raise ValueError(f"No base_commit found for instance_id='{instance_id}'")
    print(f"[Processing]:  {path} {base_commit}")
    subprocess.run(
        ["git", "checkout", base_commit],
        cwd=str(path),
        check=True
    )

    print(f"✅ Successfully checked out {path} to commit {base_commit}")

if __name__ == "__main__":
    dir_name = Path(TEST_BED)/PROJECT_NAME
    id = INSTANCE_ID
    checkout_to_base_commit(id,dir_name)
    update_database_in_conf(id)
    restart_neo4j()

    
