from __future__ import with_statement
from os.path import exists, getmtime, dirname, join, exists, basename, splitext, isdir, abspath
from os import listdir, mkdir, sep
from ConfigParser import ConfigParser, NoSectionError, NoOptionError
import subprocess
import io
from collections import namedtuple
import traceback
import codecs
from greenlet import greenlet

SourceFile = namedtuple('SourceFile', 'path code dependencies binary')

src_cache = {}

def sys_call(args,cwd=None): #now greenlet enabled!
    call = subprocess.Popen(args, cwd=cwd, shell=True, stdout=subprocess.PIPE)
    pg = greenlet.getcurrent().parent
    if pg is None:
        ret = call.wait()
    else:
        ret = None
        while ret is None:
            ret = call.poll()
            pg.switch()
    if ret != 0:
        raise Exception('call failed: ' + args)
    return call.stdout.read()
    
#takes a list of functions, executes them in semi-parallel using greenlets, and yields the results.  Not guaranteed to return results in the same order.
def gr_list(funcs):
    greenlets = [greenlet(f) for f in funcs]
    done = False
    while not done:
        done = True
        for g in greenlets:
            if not g.dead:
                r = g.switch()
                if g.dead:
                    yield r
                else:
                    done = False
 

#returns the SourceFile as a string of its dependencies followed by its code
def merge_source_file(sourcefile):
    if sourcefile.binary: raise Exception('cannot call merge_source_file on a binary file')
    sorted = []
    def add(sf, stack):
        for d in sf.dependencies:
            if d in stack: raise Exception('circular dependency: ' + sf.path + ' and ' + d.path)
            if d not in sorted: add(d, stack + [d])
        sorted.append(sf)
    add(sourcefile, [sourcefile])
    return '\n'.join([f.code for f in sorted])
    
TEXT_FILES = ['.html', '.css', '.js', '.include'] #.coffee gets compiled to js prior to this step: pass through depends commands in a comment to the generated js
def load_source_file(path, config = {}):
    """
    Translates a path to a file into a SourceFile object
    """
    if not src_cache.has_key(path):
        src_cache[path] = 'in progress'
        if splitext(path)[1] in TEXT_FILES:
            start = '<?'
            end = '?>'
            include = 'include'
            depends = 'depends'
            get = 'get'
            gitv = 'gitv'
            
            code = []
            dependencies = []
            
            with codecs.open(path, 'r', 'utf-8') as file:
                try:
                    for l in file:
                        while True:
                            inc = l.find(start)
                            if (inc == -1):
                                code.append(l)
                                break
                            code.append(l[:inc])
                            space = l.find(' ', inc + len(start))
                            command = l[inc + len(start):space]
                            e = l.find(end, space + len(' '))
                            fn = l[space:e].strip()
                            if command not in [get, include, depends, gitv]:
                                print "skipping command: " + l[inc:e+len(end)]
                                code.append(l[inc:e+len(end)])
                            else:
                                try:
                                    if command == get:
                                        code.append(config[fn])
                                    elif command == gitv:
                                        fn = fn.split('|')
                                        if len(fn) == 1: fn += [fn[0]]
                                        print 'about to check: ' + fn[0]
                                        thing = sys_call('git log -n 1 -- ' + fn[0], cwd=project_to_path(path_to_project(path)))
                                        print 'finished checking: ' + fn[0]
                                        try:
                                            thing = thing.split()[1]
                                        except:
                                            raise Exception('bad return from git log:\n' + thing)
                                        code.append(fn[1] + '?v=' + thing)
                                    else:
                                        file = load_source_file(resolve_import(fn, path_to_project(path)), config)
                                        if command == include:
                                            code.append(merge_source_file(file))
                                        elif command == depends:
                                            dependencies.append(file)
                                        else:
                                            raise Exception('unrecognized command ' + command)
                                except Exception, e:
                                    traceback.print_exc()
                                    raise Exception('Error processing ' + command + ' ' + fn + ' in file ' + path, e)
                            l = l[e + len(end):]
                except Exception:
                    print "ERROR trying to read in " + path
                    raise
            sf = SourceFile(path=path, code=''.join(code), dependencies=dependencies, binary=False)
        else:
            sf = SourceFile(path=path, code=None, dependencies=[], binary=True)
        src_cache[path] = sf
    else:
        while src_cache[path] == 'in progress':
            greenlet.getcurrent().parent.switch()
    return src_cache[path]


class JWLReader:
    """Loads a project into memory and provides parsing, compilation, and querying servics on it"""
    def __init__(self, project):
        self.project = project
        self.path = project_to_path(project)
        
        self.resources = join(self.path, 'resource')
        
        configini = join(self.path, 'config.ini')
        self._config = ConfigParser()
        self._config.read(configini)
        
        self.server_prefix = self.config('url', 'server_prefix')
        self.resource_prefix = self.config('url', 'resource_prefix')
        self.userfile_prefix = self.config('url', 'userfile_prefix')
        
    def config(self, section, value, allow_none = False):
        try:
            return self._config.get(section, value)
        except NoSectionError:
            if allow_none:
                return None
            raise Exception('Configuration file is missing section ' + section)
        except NoOptionError:
            if allow_none:
                return None
            raise Exception('Configuration file section ' + section + ' is missing key ' + value)
            
    def config_items(self, section):
        return self._config.items(section)
            
    def list_python(self):
        """returns a list of paths to python files in the root folder"""
        return [join(self.path, file) for file in listdir(self.path) if splitext(file)[1] == '.py']
        
    def compile_coffee(self, path = None):
        """Compiles coffee files into js files"""
        if path is None: path = self.path
        for file in listdir(path):
            if isdir(join(path, file)): self.compile_coffee(join(path, file))
            if splitext(file)[1] == '.coffee':
                if not exists(join(path, splitext(file)[0]) + '.js') or getmtime(join(path, file)) > getmtime(join(path, splitext(file)[0]) + '.js'):
                    print "executing: " + 'coffee %s %s'%(join(path, file), join(path, splitext(file)[0]) + '.js')
                    try: # windows
                        sys_call('coffee %s %s'%(join(path, file), join(path, splitext(file)[0]) + '.js'))
                    except: #mac
                        sys_call('coffee -c %s'%join(path, file))
                else:
                    print "file is already compiled: " + join(path, file)
        
    def get_html(self, config = {}):
        """returns a list of SourceFiles corresponding to html files in the root folder"""
        def f(file): return lambda: load_source_file(join(self.path, file), config)
        return gr_list([f(file) for file in listdir(self.path) if splitext(file)[1] == '.html'])
        
    def get_resources(self, config = {}):
        """returns an iterable of SourceFiles corresponding to files in the resources folder"""
        def get_r(dir):
            for file in listdir(dir):
                if isdir(join(dir, file)):
                    for ret in get_r(join(dir, file)): yield ret
                else:
                    def f(dir, file): return lambda: load_source_file(join(dir, file), config)
                    yield f(dir, file)
        return gr_list(get_r(self.resources))
    
def need_regen(target, sources):
    """given a target and its sources, does the target need to be regenerated?"""
    if not exists(target):
        return True
    mtime = getmtime(target)
    for source in sources:
        if getmtime(source) > mtime:
            return True
    return False
    
def gen(target, string):
    """convenience method for writing a string to a file"""
    with codecs.open(target, 'w', 'utf-8') as f:
        f.write(unicode(string))
    
def project_to_path(name):
    """Takes the project name, returns the path to it"""
    ret = False
    for p in path:
        for n in listdir(p):
            if n == name:
                if ret:
                    raise Exception("ambigous module name: " + n)
                ret = join(p, n)
    if ret:
        return ret
    raise Exception("could not find module " + name + " in path " + repr(path))
    
def path_to_project(file_path):
    """inverse of project_to_path, works on paths for files within a project"""
    for p in path:
        for n in listdir(p):
            if join(p, n) + sep in file_path:
                return n
    raise Exception("could not find a project that contains path " + file_path)
    
def resolve_import(name, current_project):
    """Takes a string of form 'projectname/subdir/file.ext' or '/subdir/file.ext' and returns the path to the file"""
    name = name.split('/')
    project_name = name.pop(0)
    if project_name == '': project_name = current_project
    path = project_to_path(project_name)
    while len(name) > 0:
        path = join(path, name.pop(0))
    return path
    
def load_import(name):
    """returns ([imports], [lines])"""
    path = resolve_import(name)
    f = codecs.open(path, 'r', 'utf-8')
    imports = []
    lines = []
    for line in f:
        pieces = line.split()
        if len(pieces) > 0 and pieces[0] == 'import':
            imports.append(pieces[1])
        elif len(pieces) > 0:
            lines = [line]
            break
    lines.extend([line for line in f])
    f.close()
    return (imports, lines)

def consolidate_files(name):
    #print "consolidating " + str(name)
    """Given the name of a file, loads the files and all its imports"""
    importqueue = [name]
    imported = []
    output = []
    while len(importqueue) > 0:
        toimport = importqueue.pop()
        #print "toimport: " + str(toimport)
        imported.append(toimport)
        imports, lines = load_import(toimport)
        importqueue.extend([l for l in imports if l not in imported])
        output.append(''.join(lines))
    return output
