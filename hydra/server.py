from fastapi import FastAPI, Body
from pydantic import BaseModel
from pathlib import Path
import json
import os


app = FastAPI()
vhosts = json.load(open('.hydra/vhosts'))


class PatchPath(BaseModel):
    path: str
    id: str


@app.get("/{repo_base:str}/{repo_name:str}/patches/{full_path:path}")
async def get_patch(repo_base: str, repo_name: str, full_path: str):
    retval = {}
    path = Path(full_path).parent
    patch_id = Path(full_path).name
    if not path or not patch_id:
        return {}
    repo_path = vhosts[repo_base][repo_name]
    with open(os.path.join(repo_path, f'.hydra/patches/{path}.{patch_id}.diff')) as diff_f:
        retval['diff'] = diff_f.read()
    retval['json'] = json.load(open(os.path.join(repo_path, f'.hydra/patches/{path}.{patch_id}.json')))
    return retval


@app.get("/{repo_base:str}/{repo_name:str}/tags")
async def get_tags(repo_base: str, repo_name: str):
    retval = {'tags': []}
    repo_path = vhosts[repo_base][repo_name]
    for file in os.listdir(os.path.join(repo_path, '.hydra/tags')):
        if file == 'current':
            continue
        retval['tags'].append(file)
    return retval


@app.get("/{repo_base:str}/{repo_name:str}/tags/{tag:str}")
async def get_tags(repo_base: str, repo_name: str, tag: str):
    repo_path = vhosts[repo_base][repo_name]
    return json.load(open(os.path.join(repo_path, f'.hydra/tags/{tag}')))
