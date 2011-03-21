from __future__ import with_statement
from os.path import dirname, join, exists, basename, splitext, isdir
from os import listdir, mkdir, makedirs, remove, chdir
import subprocess
from shutil import rmtree
import sys
import shutil
from jwl_make_lib import JWLReader, gen, need_regen, merge_source_file, project_to_path, clean_path
#import fabric.api as fab

def sys_call(args,cwd=None):
    ret = subprocess.call(args, cwd=cwd, shell=True)
    if ret != 0:
        raise Exception('call failed: ' + args)
        
def do_action(project, actionargs, deploypath, global_config):
    dependspath = join(deploypath, 'depends')
    codepath = join(deploypath, 'code')
    
    reader = JWLReader(project)
    
    if exists(codepath):
        rmtree(codepath)
    makedirs(codepath)
    
    if not exists(dependspath):
        makedirs(dependspath)
        
   
    #create the html pages
    for sourcefile in reader.get_html():
        gen(join(codepath, basename(sourcefile.path)), merge_source_file(sourcefile))
        #pagenames.append(basename(sourcefile.path).rsplit('.', 1)[0])
 
 
    #copy over any raw python files
    for file in reader.list_python():
        shutil.copy(file, join(codepath, basename(file)))
    
    print 'fetching dependencies'
    
    #fetch the dependencies
    depends = reader.config_items('depends')
    for name, url in depends:
        dpath = join(dependspath, name)
        if url.startswith('local:'):
            url = url[6:]
            if exists(dpath):
                rmtree(dpath)
            shutil.copytree(url, dpath, ignore=shutil.ignore_patterns('*.git', '*.svn'))
        else:
            if not exists(dpath):
                try:
                    makedirs(dpath)
                    sys_call('git init', dpath)
                    #sys_call('git remote add origin ' + url, dpath)
                except:
                    rmtree(dpath)
                    raise
            sys_call('git pull ' + url + ' master', dpath)
    
    #revert to the old path, then add dependencies
    del sys.path[:]
    sys.path.extend(clean_path)
    sys.path.append(dependspath)
    sys.path.append(codepath)
    
    from jwl import deployconfig
    from jwl.DB.hashdb import HashDB
    deployconfig.set(dbengine=HashDB)
    deployconfig.set(debug=True)
    
    import index
    from jwl.tornado_launch import launch
    print 'starting local server...'
    launch(index.main, reader.server_prefix, int(global_config.get('local', 'port')))
