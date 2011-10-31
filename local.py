import remote
from remote import sys_call
from os.path import dirname, join, exists, basename, splitext, isdir, relpath
from os import listdir, mkdir, makedirs, remove, chdir
        
def do_action(project, actionargs, deploypath, global_config):
    server_path = join(deploypath, 'local_server')
    extra_env = {
        'env.basic.deploypath': server_path,
        'env.basic.deployrepo': server_path,
        'env.basic.debug': True,
        'env.basic.host': 'localhost',
        'env.basic.startcommand': 'python ' + server_path + '/code/launch_server.py',
        'env.basic.port': '2020'
    }
    if not exists(server_path):
        makedirs(server_path)
        sys_call('git init', server_path)
        sys_call("echo logs >> .gitignore", server_path)
        sys_call("echo *.pyo >> .gitignore", server_path)
        sys_call("echo *.pyc >> .gitignore", server_path)
        sys_call("echo generated >> .gitignore", server_path)
        
        sys_call("git add *", server_path)
        sys_call('git commit -m "initial commit"', server_path)
        sys_call("git branch uploaded", server_path)
        
    remote.do_action(project, ['local', 'CURRENT'], deploypath, global_config, extra_env)