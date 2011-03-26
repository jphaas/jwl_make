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

# def sys_call(args,cwd=None):
    # ret = subprocess.call(args, cwd=cwd, shell=True)
    # if ret != 0:
        # raise Exception('call failed: ' + args)
        
def do_action(project, actionargs, deploypath, global_config):
    target = actionargs[0]
    deploypath = join(deploypath, target)

    dependspath = join(deploypath, 'depends')
    codepath = join(deploypath, 'code')
    staticpath = join(deploypath, 'static')
    htmlpath = join(deploypath, 'html')
    
    
    #server_side paths
    server_dependspath = ""
    server_codepath = "" 
    server_staticpath = ""
    server_htmlpath = ""
    rserver_dependspath = repr(server_dependspath)
    rserver_codepath = repr(server_codepath)
    rserver_staticpath = repr(server_staticpath)
    rserver_htmlpath = repr(server_htmlpath)
    
    reader = JWLReader(project)
    
    for p in (dependspath, codepath, htmlpath):
        if exists(p):
            rmtree(p)
        makedirs(p)
        
    #SETUP DEPLOY CONFIG
    envkey = target + '_'
    dplines = ['from jwl import deployconfig']
    config_data = {}
    for section in reader._config.sections():
        if section.startswith(envkey):
            for key, value in reader._config.items(section):
                sectiontitle = section[len(envkey):]
                rvalue = repr(value)
                dplines.append("deployconfig.set2('env.%(sectiontitle)s.%(key)s', %(rvalue)s)"%locals())
                config_data['env.' + section[len(envkey):] + '.' + key] = value
    
    gen(join(codepath, 'deployconfig_init.py'), '\n'.join(dplines))
    
    #legacy...
    config_data['facebook_app_id'] = config_data['env.facebook.facebook_app_id']
        
    urlhandlers = []
    #create the html pages
    for sourcefile in reader.get_html(config_data):
        stripped_name = basename(sourcefile.path).rsplit('.', 1)[0]
        gen(join(htmlpath, stripped_name), merge_source_file(sourcefile))
        urlhandlers.append('urlhandlers.append((r"/(%(stripped_name)s)", tornado.web.StaticFileHandler, {"path": %(rserver_htmlpath)s}))'%locals())
 
    urlhandlers.append('urlhandlers.append((r"/()", tornado.web.StaticFileHandler, {"path": %(rserver_htmlpath)s, "default_filename": "index"}))'%locals())
    
    #copy over resources
    if exists(staticpath):
        rmtree(staticpath)
    shutil.copytree(reader.resources, staticpath)
    rprefix = reader.resource_prefix
    urlhandlers.append('urlhandlers.append((r"/%(rprefix)s/(.*)", tornado.web.StaticFileHandler, {"path": %(rserver_staticpath)s}))'%locals())
 
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
    
    cookie_secret = repr(reader.config('basic', 'cookie_secret'))
    
    # deal with in a non-legacy way at some point?
    
    # google_consumer_key = reader.config('google', 'consumer_key')
    # google_consumer_secret = reader.config('google', 'consumer_secret')
    
    
    #build server_interface.js
    server_interface_path = resolve_import('jwl_make2/server_interface.js', None)
    del sys.path[:]
    sys.path.extend(clean_path)
    sys.path.append(dependspath)
    sys.path.append(codepath)
    import index
    from jwl.remote_method import make_dummy_handler
    
    with open(join(htmlpath, 'server_interface.js'), 'w') as f:
        f.write('var server = "%s";'%reader.server_prefix)
        with open(server_interface_path, 'r') as f2:
            f.write(f2.read())
        f.write('\n')
        f.write(make_dummy_handler(index.main).write_js_interface())
        
    urlhandlers.append('urlhandlers.append((r"/(server_interface.js)", tornado.web.StaticFileHandler, {"path": %(rserver_htmlpath)s}))'%locals())
    
    urlhandlercode = '\n'.join(urlhandlers)
    
    readerserverprefix = reader.server_prefix
            
    #build the execution file
    launch_server = r"""
sys.path.append(%(rserver_dependspath)s)
sys.path.append(%(rserver_codepath)s)

import deployconfig_init

# from jwl import deployconfig
# from jwl.DB.hashdb import HashDB
# deployconfig.set(dbengine=HashDB)
# deployconfig.set(debug=True)
   
import index
from jwl.tornado_launch import launch
from jwl.remote_method import make_dummy_handler

%(urlhandlercode)s 

#GOOGLE LOGIN
# from jwl.googleauth import LoginController
# urlhandlers.append((r"/auth/(.*)", LoginController))

print 'starting server...'
urlhandlers.append((r"/%(readerserverprefix)s", index.main))
application = tornado.web.Application(urlhandlers, cookie_secret=%(cookie_secret)s)#, google_consumer_key=google_consumer_key, google_consumer_secret=google_consumer_secret)

launch(application, 80)
    """%locals()
    
    gen(join(codepath, 'launch_server.py'), launch_server)