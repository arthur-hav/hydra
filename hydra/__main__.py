import os
import sys
import uuid
import subprocess
import json
import datetime
from pathlib import Path
import shutil
from distutils.dir_util import copy_tree
import multiprocessing


HYDRAIGNORE = ['.hydra']


def commit_patch(diffdir, path, file):
    patch_id = uuid.uuid4().hex
    context = Context.create()
    type_patch = 'update'
    flags = []
    posix_p = Path(os.path.join(path, file)).as_posix()
    if not os.path.exists(os.path.join('.hydra/images/current', path, file)):
        flags = ['-N']
        type_patch = 'create'
        Path(diffdir).mkdir(parents=True, exist_ok=True)
    if not os.path.exists(posix_p):
        flags = ['-N']
        type_patch = 'delete'
        os.unlink(os.path.join('.hydra/images/current', path, file))
        context.ver_files.remove(posix_p)

    diff = subprocess.run(['diff',
                           '-u'] + flags + [
                              os.path.join('.hydra/images/current', path, file),
                              os.path.join(path, file)],
                          stdout=subprocess.PIPE)
    if diff.returncode == 0 and type_patch == 'update':
        return None

    diffpath = os.path.join(diffdir, f'{file}.{patch_id}.diff')
    jsonpath = os.path.join(diffdir, f'{file}.{patch_id}.json')
    with open(diffpath, 'wb') as f:
        f.write(diff.stdout)
    with open(jsonpath, 'w') as f:
        f.write(json.dumps({
            'timestamp': datetime.datetime.now().isoformat(),
            'tag': context.id,
            'type': type_patch,
            }))
    if type_patch != 'delete':
        shutil.copy(posix_p, os.path.join(f'.hydra/images/current', path, file))
    print(f"{type_patch[0]} {patch_id}: {posix_p}")
    context.save()
    return patch_id


def patch_file(path, patch_ids, flags=None):
    if flags is None:
        flags = []
    max_retval = 0
    for patch_id in patch_ids:
        patch_data = json.load(open(os.path.join('.hydra/patches', f'{path}.{patch_id}.json')))
        if patch_data['type'] == 'create':
            Path(os.path.join('.hydra/images/current', path)).touch()
        result = subprocess.run(['patch',
                                 '--posix',
                                 '-u',
                                 '--quiet',
                                 ] + flags + [
                                 os.path.join('.hydra/images/current', path),
                                 os.path.join('.hydra/patches', f'{path}.{patch_id}.diff')])
        max_retval = max(result.returncode, max_retval)
    return max_retval


def hydra_commit():
    context = Context.create()
    patch_ids = {}
    for full_path in context.ver_files:
        posix_p = Path(full_path).as_posix()
        path = Path(full_path).parent
        file = Path(full_path).name
        diffdir = os.path.join('.hydra/patches', path)
        patch_id = commit_patch(diffdir, path, file)
        if patch_id is not None:
            patch_ids[posix_p] = patch_id
    for k, v in patch_ids.items():
        if k in context.commits:
            context.commits[k].append(v)
        else:
            context.commits[k] = [v]
    if patch_ids:
        hydra_tag()


def hydra_tag():
    context = Context.create()
    new_tag = uuid.uuid4().hex
    with open(f'.hydra/tags/{new_tag}', 'w') as f:
        f.write(json.dumps({'id': new_tag,
                            'patches': context.commits,
                            'ancestors': context.ancestors,
                            'ver_files': list(context.ver_files)}))
    shutil.copy(f'.hydra/tags/{new_tag}', '.hydra/tags/current')
    print(f'New tag: {new_tag}')


def reset(path):
    if os.path.isdir(path):
        copy_tree(os.path.join('.hydra/images/current', path), path)
    else:
        shutil.copy(os.path.join('.hydra/images/current', path), path)


def hydra_set_tag(tag):
    with open(f'.hydra/tags/{tag}') as f:
        tag_data = json.loads(f.read())
    tag_from = tag_data['ancestors'][-1]
    tag_patches = tag_data['patches']
    shutil.rmtree('.hydra/images/current')
    shutil.copytree(f'.hydra/images/{tag_from}', '.hydra/images/current')

    with multiprocessing.Pool(processes=4) as pool:
        pool.starmap(patch_file, [[path, patch_ids] for path, patch_ids in tag_patches.items()])

    shutil.copy(f'.hydra/tags/{tag}', '.hydra/tags/current')


def get_commits_from(ancestor, tag):
    with open(f'.hydra/tags/{tag}') as f:
        tag_data = json.loads(f.read())
    acc = tag_data['patches']
    for current_tag in tag_data['ancestors'][::-1]:
        with open(f'.hydra/tags/{current_tag}') as f:
            cur_tag_data = json.loads(f.read())
        for k, v in cur_tag_data['patches'].items():
            if k in acc:
                acc[k] = v + acc[k]
            else:
                acc[k] = v
        if ancestor == current_tag:
            break
    return acc


class Context:
    _instance = None

    @classmethod
    def create(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        with open(f'.hydra/tags/current') as f:
            data = json.loads(f.read())
            self.commits = data['patches']
            self.ver_files = set(data['ver_files'])
            self.ancestors = data['ancestors']
            self.id = data['id']

    def save(self):
        with open(f'.hydra/tags/current', 'w') as f:
            f.write(json.dumps({'id': self.id,
                                'patches': self.commits,
                                'ver_files': list(self.ver_files),
                                'ancestors': self.ancestors}))


def main():
    if sys.argv[1] == 'create':
        repo_base = os.getlogin()
        repo_name = sys.argv[2]
        os.mkdir(repo_name)
        os.mkdir(f'{repo_name}/.hydra')
        os.mkdir(f'{repo_name}/.hydra/patches')
        os.mkdir(f'{repo_name}/.hydra/images')
        os.mkdir(f'{repo_name}/.hydra/images/root')
        os.mkdir(f'{repo_name}/.hydra/images/current')
        os.mkdir(f'{repo_name}/.hydra/tags')
        with open(f'{repo_name}/.hydra/tags/root', 'w') as f:
            f.write(json.dumps({'id': 'root', 'patches': {}, 'ancestors': ['root'], 'ver_files': []}))
        with open(f'{repo_name}/.hydra/vhosts', 'w') as f:
            f.write(json.dumps({repo_base: {repo_name: '.'}}))
        shutil.copy(f'{repo_name}/.hydra/tags/root', f'{repo_name}/.hydra/tags/current')

    elif sys.argv[1] == 'add':
        context = Context.create()
        bfs = sys.argv[2:]
        while bfs:
            path = Path(bfs.pop(0)).as_posix()
            if path in HYDRAIGNORE:
                continue
            if os.path.isdir(path):
                for file in os.listdir(path):
                    if file in HYDRAIGNORE:
                        continue
                    bfs.append(os.path.join(path, file))
            elif os.path.isfile(path):
                posix_p = Path(path).as_posix()
                context.ver_files.add(posix_p)
        context.save()

    elif sys.argv[1] == 'commit':
        hydra_commit()

    elif sys.argv[1] == 'set-tag':
        if len(sys.argv) > 2:
            hydra_set_tag(sys.argv[2])

    elif sys.argv[1] == 'snap':
        context = Context.create()
        context.ancestors.append(context.id)
        context.commits = {}
        shutil.copytree('.hydra/images/current', f'.hydra/images/{context.id}')
        hydra_tag()

    elif sys.argv[1] == 'reset':
        if len(sys.argv) == 2:
            reset('.')
        else:
            reset(sys.argv[2])

    elif sys.argv[1] == 'merge':
        context = Context.create()
        nearest_common_ancestor = 'root'
        with open(f'.hydra/tags/{sys.argv[2]}') as f:
            target_data = json.loads(f.read())
        if target_data['ancestors'] != context.ancestors:
            common_ancestors = set(target_data['ancestors']) - set(context.ancestors)
            nearest_common_ancestor = max(common_ancestors, key=lambda a: context.ancestors.index(a))
        context_patches = get_commits_from(nearest_common_ancestor, context.id)
        target_patches = get_commits_from(nearest_common_ancestor, sys.argv[2])
        status = 0
        for path, patches in target_patches.items():
            to_merge = sorted(set(patches) - set(context_patches.get(path, [])), key=lambda p: patches.index(p))
            status = max(status, patch_file(path, to_merge, ['--merge']))
            reset(path)
        if status == 0:
            hydra_commit()
        else:
            print("Merge produced conflicts. Resolve them then commit.")

    else:
        print(f"Unkonwn command hydra {sys.argv[1]}.")


if __name__ == '__main__':
    main()
