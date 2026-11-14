"""Owner-uploaded images, stored locally and copied only into their job's inputs."""
import hashlib
import re
import struct


def selected(chat,task,uploads):
    images=[u['image_id'] for u in (uploads or []) if u.get('image_id')]
    if not images and not re.search(r'\b(new topic|new task|start over|unrelated question)\b',task,re.I):
        previous=next((m for m in reversed((chat or {}).get('messages',[])[-6:]) if m.get('role')=='user' and 'image_ids' in m),None)
        images=list((previous or {}).get('image_ids') or [])
    return images


def dimensions(data,suffix):
    if suffix=='.png' and data.startswith(b'\x89PNG\r\n\x1a\n') and data[12:16]==b'IHDR' and len(data)>32 and data[-8:-4]==b'IEND':
        return struct.unpack('>II',data[16:24])
    if suffix in ('.jpg','.jpeg') and data.startswith(b'\xff\xd8') and data.endswith(b'\xff\xd9'):
        index=2
        while index+4<len(data):
            if data[index]!=255:break
            marker=data[index+1];length=int.from_bytes(data[index+2:index+4],'big')
            if length<2 or index+2+length>len(data):break
            if marker in (0xc0,0xc1,0xc2) and length>=8:
                height,width=struct.unpack('>HH',data[index+5:index+9]);return width,height
            index+=2+length
    raise ValueError('This is not a supported PNG or JPEG image.')


def store(cfg,name,data):
    from pathlib import Path
    suffix=Path(name).suffix.lower();width,height=dimensions(data,suffix)
    if not 0<width<=12000 or not 0<height<=12000 or width*height>20000000:raise ValueError('Image dimensions exceed the 20-megapixel limit.')
    identity=hashlib.sha256(data).hexdigest();folder=cfg.state_dir/'image-inputs';folder.mkdir(parents=True,exist_ok=True)
    destination=folder/(identity+('.png' if suffix=='.png' else '.jpg'))
    if destination.is_symlink() or not destination.resolve().is_relative_to(cfg.state_dir.resolve()):raise ValueError('Unsafe image storage path.')
    if not destination.exists():destination.write_bytes(data)
    return {'name':name,'image_id':destination.name,'mime':'image/png' if suffix=='.png' else 'image/jpeg','width':width,'height':height,'notes':['Image data is passed only when you send the attached draft; text token estimates exclude image usage.'],'truncated':False}


def validate(cfg,values):
    if not isinstance(values,list) or len(values)>3:raise ValueError('Attach at most three images.')
    folder=(cfg.state_dir/'image-inputs').resolve();result=[]
    if not folder.is_relative_to(cfg.state_dir.resolve()):raise ValueError('Unsafe image storage folder.')
    for value in values:
        if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}\.(png|jpg)',value):raise ValueError('Invalid image attachment.')
        path=folder/value
        if path.is_symlink() or not path.is_file() or path.stat().st_size>1000000:raise ValueError('Image attachment is unavailable.')
        data=path.read_bytes()
        if hashlib.sha256(data).hexdigest()!=value.split('.')[0]:raise ValueError('Image attachment checksum changed.')
        dimensions(data,path.suffix);result.append(path)
    return result


def prepare(cfg,values,work):
    paths=validate(cfg,values);folder=work/'image-inputs';result=[]
    if folder.is_symlink() or not folder.resolve().is_relative_to(work.resolve()):raise ValueError('Unsafe job image folder.')
    if paths:folder.mkdir(parents=True,exist_ok=True)
    for source in paths:
        destination=folder/source.name
        if destination.is_symlink():raise ValueError('Unsafe job image file.')
        if destination.exists() and destination.read_bytes()!=source.read_bytes():raise ValueError('Reserved job image input was changed.')
        if not destination.exists():destination.write_bytes(source.read_bytes())
        result.append(destination)
    return result
