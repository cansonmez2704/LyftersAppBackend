import os , magic
from django.core.exceptions import ValidationError
from django.conf import settings  


def validate_real_content_type(file):
   
    valid_mime_types = [
        'image/jpeg',
        'image/png',
        'image/gif',
        'video/mp4',
        'video/x-msvideo',  
        'video/quicktime',  
        'video/x-matroska', 
        'video/webm'
    ]

    initial_position = file.tell()
    
    file.seek(0)
    file_chunk = file.read(2048)
    
    file.seek(initial_position)
    mime_type = magic.from_buffer(file_chunk, mime=True)

    if mime_type not in valid_mime_types:
        raise ValidationError(
            f"Unsupported file content detected. The file appears to be '{mime_type}', which is not allowed."
        )

def validate_media_size(file):
    image_exts = ['.jpg', '.jpeg', '.png', '.gif']
    video_exts = ['.mp4', '.avi', '.mov', '.mkv', '.webm']

    ext = os.path.splitext(file.name)[1].lower()

    actual_size_mb = file.size / (1024 * 1024)

    if ext in image_exts:
        if file.size > settings.MAX_IMAGE_UPLOAD_SIZE:
            limit_mb = settings.MAX_IMAGE_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(
                f"Images cannot exceed {limit_mb:.0f} MB. Your file is {actual_size_mb:.2f} MB."
            )
            
    elif ext in video_exts:
        if file.size > settings.MAX_VIDEO_UPLOAD_SIZE:
            limit_mb = settings.MAX_VIDEO_UPLOAD_SIZE / (1024 * 1024)
            raise ValidationError(
                f"Videos cannot exceed {limit_mb:.0f} MB. Your file is {actual_size_mb:.2f} MB."
            )