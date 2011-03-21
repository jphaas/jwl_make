from __future__ import with_statement
from os.path import dirname, join, exists, basename, splitext, isdir
from os import listdir, mkdir, makedirs, remove, chdir
import subprocess
from shutil import rmtree
import sys
import shutil
from jwl_make_lib import JWLReader, gen, need_regen, merge_source_file, project_to_path, clean_path, resolve_import
import tornado.web, tornado.auth
#import fabric.api as fab

def sys_call(args,cwd=None):
    ret = subprocess.call(args, cwd=cwd, shell=True)
    if ret != 0:
        raise Exception('call failed: ' + args)
        
def do_action(project, actionargs, deploypath, global_config):
    dependspath = join(deploypath, 'depends')
    codepath = join(deploypath, 'code')
    staticpath = join(deploypath, 'static')
    htmlpath = join(deploypath, 'html')
    
    reader = JWLReader(project)
    
    for p in (dependspath, codepath, staticpath, htmlpath):
        if exists(p):
            rmtree(p)
        makedirs(p)
        
    urlhandlers = []
    #create the html pages
    for sourcefile in reader.get_html():
        stripped_name = basename(sourcefile.path).rsplit('.', 1)[0]
        gen(join(htmlpath, stripped_name), merge_source_file(sourcefile))
        urlhandlers.append((r"/(%s)"%stripped_name, tornado.web.StaticFileHandler, {"path": htmlpath}))
        #pagenames.append(basename(sourcefile.path).rsplit('.', 1)[0])
 
    urlhandlers.append((r"/()", tornado.web.StaticFileHandler, {"path": htmlpath, "default_filename": "index"}))
 
    #copy over any raw python files
    for file in reader.list_python():
        shutil.copy(file, join(codepath, basename(file)))
        
    
    #get the javascript necessary for server_interface
    server_interface_path = resolve_import('jwl_make2/server_interface.js', None)
    
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
               
    
    cookie_secret = reader.config('basic', 'cookie_secret')
    google_consumer_key = reader.config('google', 'consumer_key')
    google_consumer_secret = reader.config('google', 'consumer_secret')
    
               
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
    from jwl.remote_method import make_dummy_handler
    
    #write javascript function handlers
    from jwl import remote_method
    
    with open(join(htmlpath, 'server_interface.js'), 'w') as f:
        f.write('var server = "%s";'%reader.server_prefix)
        with open(server_interface_path, 'r') as f2:
            f.write(f2.read())
        f.write('\n')
        f.write(make_dummy_handler(index.main).write_js_interface())
        
    urlhandlers.append((r"/(server_interface.js)", tornado.web.StaticFileHandler, {"path": htmlpath}))
    
    
    #GOOGLE LOGIN
    from jwl.googleauth import LoginController
    urlhandlers.append((r"/auth/(.*)", LoginController))
    
    
    print 'starting local server...'
    urlhandlers.append((r"/" + reader.server_prefix, index.main))
    application = tornado.web.Application(urlhandlers, cookie_secret=cookie_secret, google_consumer_key=google_consumer_key, google_consumer_secret=google_consumer_secret)
 
    launch(application, int(global_config.get('local', 'port')))
