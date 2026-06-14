import io
import os
from PIL import Image
from django.core.files.uploadedfile import InMemoryUploadedFile

def optimize_logo(uploaded_file, max_size=(512, 512), format='WEBP', quality=85):
    """
    Optimizes an uploaded image file by converting to RGBA, resizing to max_size,
    and saving it in the specified format (default WEBP) to reduce file size.
    """
    try:
        # Open image from uploaded file
        img = Image.open(uploaded_file)
        
        # Convert to RGBA to preserve transparency if it's a PNG/WEBP
        if img.mode != 'RGBA':
            img = img.convert('RGBA')
            
        # Resize using LANCZOS for high quality downsampling
        img.thumbnail(max_size, Image.Resampling.LANCZOS)
        
        # Save to BytesIO
        output_io = io.BytesIO()
        img.save(output_io, format=format, quality=quality)
        
        # Calculate new size
        output_io.seek(0, os.SEEK_END)
        size = output_io.tell()
        output_io.seek(0)
        
        # Determine new filename extension
        original_name, _ = os.path.splitext(uploaded_file.name)
        new_filename = f"{original_name}.{format.lower()}"
        
        # Create a new InMemoryUploadedFile
        content_type = f"image/{format.lower()}"
        optimized_file = InMemoryUploadedFile(
            file=output_io,
            field_name=None,
            name=new_filename,
            content_type=content_type,
            size=size,
            charset=None
        )
        return optimized_file
    except Exception as e:
        # Fallback to the original file if processing fails
        print(f"Error optimizing logo: {e}")
        return uploaded_file
