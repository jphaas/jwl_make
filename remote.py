from __future__ import with_statement
from os.path import dirname, join, exists, basename, splitext, isdir, relpath
from os import listdir, mkdir, makedirs, remove, chdir
import os
import subprocess
from shutil import rmtree
import sys
import shutil
from jwl_make import JWLReader, gen, need_regen, merge_source_file, project_to_path, clean_path, resolve_import
import tornado.web, tornado.auth

#patching rmtree so it can deal with readonly files
def onerror(func, path, exc_info):
    """
    Error handler for ``shutil.rmtree``.

    If the error is due to an access error (read only file)
    it attempts to add write permission and then retries.

    If the error is for another reason it re-raises the error.

    Usage : ``shutil.rmtree(path, onerror=onerror)``
    """
    import stat
    if not os.access(path, os.W_OK):
        # Is the error an access error ?
        os.chmod(path, stat.S_IWUSR)
        func(path)
    else:
        raise

def sys_call(args,cwd=None, failokay=False):
    ret = subprocess.call(args, cwd=cwd, shell=True)
    if ret != 0:
        if failokay:
            print 'warning, call failed: ' + args
        else:
            raise Exception('call failed: ' + args)
        
def do_action(project, actionargs, deploypath, global_config, extra_env = {}):
    target = actionargs[0]
    branch = 'release' if len(actionargs) < 2 else actionargs[1]
    deploypath = join(deploypath, target)

    dependspath = join(deploypath, 'depends')
    codepath = join(deploypath, 'code')
    staticpath = join(deploypath, 'static')
    htmlpath = join(deploypath, 'html')
    
      
    reader = JWLReader(project)
    
    #SWITCH TO RELEASE BRANCH
    try:
        if branch != 'CURRENT':
            sys_call('git checkout ' + branch, reader.path)
        
        reader.compile_coffee()
        
        

        
           
        #SETUP DEPLOY CONFIG
        envkey = target + '_'
        dplines = ['from jwl import deployconfig']
        config_data = {}
        for section in reader._config.sections():
            for key, value in reader._config.items(section):
                if section.startswith(envkey) or section.find('_') == -1:
                    if section.startswith(envkey):
                        sectiontitle = 'env.' + section[len(envkey):]
                    else:
                        sectiontitle = section
                    rvalue = repr(value)
                    dplines.append("deployconfig.set2('%(sectiontitle)s.%(key)s', %(rvalue)s)"%locals())
                    dplines.append("print '%(sectiontitle)s.%(key)s', '=', %(rvalue)s"%locals())
                    config_data[sectiontitle + '.' + key] = value
                    print sectiontitle + '.' + key, '=', value
        config_data['env'] = target
        for key, value in extra_env.iteritems():
            rvalue = repr(value)
            dplines.append("deployconfig.set2('%(key)s', %(rvalue)s)"%locals())
            dplines.append("print '%(key)s', '=', %(rvalue)s"%locals())
            config_data[key] = value
                    
        #server_side paths
        server_deploypath = config_data['env.basic.deploypath']
        server_dependspath = server_deploypath + '/depends'
        server_codepath = server_deploypath + '/code'
        server_staticpath = server_deploypath + '/static'
        server_htmlpath = server_deploypath + '/html'
        rserver_dependspath = repr(server_dependspath)
        rserver_codepath = repr(server_codepath)
        rserver_staticpath = repr(server_staticpath)
        rserver_htmlpath = repr(server_htmlpath)
        
            
        deployrepo = config_data['env.basic.deployrepo']
        
        if not exists(deploypath):
            makedirs(deploypath)
            sys_call('git clone ' + deployrepo + ' ' + deploypath)
            sys_call('git checkout uploaded', deploypath)
        else: #clean but don't remove the .git directory
            sys_call('git pull origin uploaded', deploypath)
            for p in (dependspath, codepath, htmlpath, staticpath):
                if exists(p): rmtree(p, onerror=onerror)
            
        for p in (dependspath, codepath, htmlpath, staticpath):
            if not exists(p): makedirs(p)
            
            
        print 'fetching dependencies'
        
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
            
        #run any custom compilation code
        if exists(join(reader.path, 'compile.py')):
            old_path = list(sys.path)
            sys.path.append(reader.path)
            sys.path.append(dependspath)
            
            import compile
            compile
            compile.run(reader)
            
            del sys.path[:]
            sys.path.extend(old_path)

        
        gen(join(codepath, 'deployconfig_init.py'), '\n'.join(dplines))
        
        #legacy...
        # config_data['facebook_app_id'] = config_data['env.facebook.facebook_app_id']
            
        urlhandlers = []
        #create the html pages
        for sourcefile in reader.get_html(config_data):
            stripped_name = basename(sourcefile.path).rsplit('.', 1)[0]
            gen(join(htmlpath, stripped_name), merge_source_file(sourcefile))
            urlhandlers.append('urlhandlers.append((r"/(%(stripped_name)s)", NoCacheStaticHandler, {"path": %(rserver_htmlpath)s}))'%locals())
     
        urlhandlers.append('urlhandlers.append((r"/()", NoCacheStaticHandler, {"path": %(rserver_htmlpath)s, "default_filename": "index"}))'%locals())
        
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
        
        rprefix = reader.resource_prefix
        urlhandlers.append('urlhandlers.append((r"/%(rprefix)s/(.*)", NoCacheStaticHandler, {"path": %(rserver_staticpath)s}))'%locals())
     
        #copy over any raw python files
        for file in reader.list_python():
            shutil.copy(file, join(codepath, basename(file)))
            
        
        cookie_secret = repr(reader.config('basic', 'cookie_secret'))
        
        # deal with in a non-legacy way at some point?
        
        # google_consumer_key = reader.config('google', 'consumer_key')
        # google_consumer_secret = reader.config('google', 'consumer_secret')
        
        
        #build server_interface.js
        server_interface_path = resolve_import('jwl_make/server_interface.js', None)
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
            
        urlhandlers.append('urlhandlers.append((r"/(server_interface.js)", NoCacheStaticHandler, {"path": %(rserver_htmlpath)s}))'%locals())
        
        urlhandlercode = '\n'.join(urlhandlers)
        
        readerserverprefix = reader.server_prefix
        
        is_debug = config_data['env.basic.debug']
        
        server_port = config_data['env.basic.port']
                
        #build the execution file
        launch_server = r"""
import sys
sys.path.append(%(rserver_dependspath)s)
sys.path.append(%(rserver_codepath)s)

import deployconfig_init
from jwl import deployconfig

deployconfig.set(debug=%(is_debug)s)
   
import index
import tornado
from jwl.tornado_launch import launch
from jwl.remote_method import make_dummy_handler, NoCacheStaticHandler

urlhandlers = []

%(urlhandlercode)s 

#GOOGLE LOGIN
# from jwl.googleauth import LoginController
# urlhandlers.append((r"/auth/(.*)", LoginController))

if __name__ == '__main__':
    urlhandlers.append((r"/%(readerserverprefix)s.*", index.main))
    print 'about to run startup code'
    index.do_startup(urlhandlers)
    application = tornado.web.Application(urlhandlers, cookie_secret=%(cookie_secret)s, gzip=True)#, google_consumer_key=google_consumer_key, google_consumer_secret=google_consumer_secret)
    index.main._my_application = application
    print 'startup code complete, starting server...'
    launch(application, %(server_port)s)
    
        """%locals()
        
        gen(join(codepath, 'launch_server.py'), launch_server)
        
        print 'about to upload...'
        
        #check in the local code to git
        sys_call('git add --all', deploypath, failokay=True)
        sys_call('git commit -a -m "automated..."', deploypath, failokay=True)
        sys_call('git push origin uploaded', deploypath)
        
        #Upload to server
        host_string = config_data['env.basic.host']
        if host_string == 'localhost':
            execute = sys_call
        else:
            import fabric.api as fab
            def execute(args, cwd, fail_okay):
                with fab.settings(host_string=host_string,key_filename=keyfile,disable_known_hosts=True):
                    with fab.cd(cwd):
                        with fab.settings(warn_only=fail_okay):
                            fab.run(args)
            keyfile = global_config.get('keys', config_data['env.basic.sshkey']) 
        
        try:
            execute('git add --all', server_deploypath, True)
            execute('git commit -a -m "saving any changes such as .pyc etc"', server_deploypath, True)
            execute('git merge uploaded', server_deploypath, False)
            execute(config_data['env.basic.startcommand'], server_deploypath, False)
        finally:
            if host_string != 'localhost':
                from fabric.state import connections
                for key in connections.keys():
                    connections[key].close()
                    del connections[key]
                
         
    finally:
        #SWITCH BACK TO MASTER BRANCH
        if branch != 'CURRENT':
            sys_call('git checkout master', reader.path)
