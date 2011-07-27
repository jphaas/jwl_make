from __future__ import with_statement
from os.path import dirname, join, exists, basename, splitext, isdir, relpath
from os import listdir, mkdir, makedirs, remove, chdir
from shutil import rmtree
import sys
import shutil
from jwl_make import JWLReader, gen, need_regen, merge_source_file, project_to_path, clean_path, resolve_import, sys_call
import tornado.web, tornado.auth
#import fabric.api as fab
        
def do_action(project, actionargs, deploypath, global_config):
    dependspath = join(deploypath, 'depends')
    codepath = join(deploypath, 'code')
    staticpath = join(deploypath, 'static')
    htmlpath = join(deploypath, 'html')
    
    reader = JWLReader(project)
    
    reader.compile_coffee()
    
    for p in (dependspath, codepath, htmlpath):
        if exists(p):
            rmtree(p)
        makedirs(p)
        
    config_data = {}
    try:
        config_data['facebook_app_id'] = global_config.get('facebook', 'facebook_appid_local')
    except NoSectionError:
        pass
        
    urlhandlers = []
    #create the html pages
    for sourcefile in reader.get_html(config_data):
        stripped_name = basename(sourcefile.path).rsplit('.', 1)[0]
        gen(join(htmlpath, stripped_name), merge_source_file(sourcefile))
        urlhandlers.append((r"/(%s)"%stripped_name, tornado.web.StaticFileHandler, {"path": htmlpath}))
        #pagenames.append(basename(sourcefile.path).rsplit('.', 1)[0])
 
    urlhandlers.append((r"/()", tornado.web.StaticFileHandler, {"path": htmlpath, "default_filename": "index"}))
    
    
    #copy over resources
    if exists(staticpath):
        rmtree(staticpath)
    for sourcefile in reader.get_resources(config_data):
        relative_path = relpath(sourcefile.path, reader.resources)
        if not exists(join(staticpath, dirname(relative_path))): makedirs(join(staticpath, dirname(relative_path)))
        if sourcefile.binary:
            shutil.copy(sourcefile.path, join(staticpath, relative_path))
        else:
            gen(join(staticpath, relative_path), merge_source_file(sourcefile))
    
    urlhandlers.append((r"/" + reader.resource_prefix + "/(.*)", tornado.web.StaticFileHandler, {"path": staticpath}))
 
    #copy over any raw python files
    for file in reader.list_python():
        shutil.copy(file, join(codepath, basename(file)))
        
    
    #get the javascript necessary for server_interface
    server_interface_path = resolve_import('jwl_make/server_interface.js', None)
    
    #fetch the dependencies
    depends = reader.config_items('depends')
    for name, url in depends:
        dpath = join(dependspath, name)
        if url.startswith('local:'):
            url = url[6:]
            ls = url.split(';')
            i = 0
            try:
                while not exists(ls[i]):
                    i += 1
            except:
                   raise Exception('could not find path ' + url) 
            url = ls[i]
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
    
    print 'cleaning sys.path...'
    
               
    #revert to the old path, then add dependencies
    del sys.path[:]
    sys.path.extend(clean_path)
    sys.path.append(dependspath)
    sys.path.append(codepath)
    
    print 'importing deployconfig + hashdb'
    from jwl import deployconfig
    from jwl.DB.hashdb import HashDB
    deployconfig.set(dbengine=HashDB)
    deployconfig.set(debug=True)
       
    print 'importing index'
    import index
    
    print 'importing tornado launch'
    from jwl.tornado_launch import launch
    print 'importing remote_method'
    from jwl.remote_method import make_dummy_handler
    
    print 'writing server_interface.js...'
    
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
    
    print 'setting up deploy config...'
    
    #SETUP DEPLOY CONFIG
    print 'setting environment variables:'
    for section in reader._config.sections():#global_config.sections():
        if section.startswith('local_'):
            for key, value in reader._config.items(section):#global_config.items(section):
                print 'env.' + section[6:] + '.' + key + ' = ' + value
                deployconfig.set2('env.' + section[6:] + '.' + key, value)
    deployconfig.set2('IS_LOCAL', True)
    deployconfig.set2('env', 'local')
    
    print 'starting local server...'
    urlhandlers.append((r"/" + reader.server_prefix, index.main))
    application = tornado.web.Application(urlhandlers, cookie_secret=cookie_secret, google_consumer_key=google_consumer_key, google_consumer_secret=google_consumer_secret)
 
    launch(application, int(global_config.get('local', 'port')))
