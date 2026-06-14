import os
from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible

@deconstructible
class SafeFileValidator:
    """
    Validates uploaded files for enterprise-grade security.
    Checks MIME type, extension, and file size.
    """
    def __init__(self, max_size_mb=5, allowed_extensions=None, allowed_mimetypes=None):
        self.max_size = max_size_mb * 1024 * 1024
        self.allowed_extensions = allowed_extensions or ['.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.webp']
        self.allowed_mimetypes = allowed_mimetypes or [
            'application/pdf', 
            'application/msword', 
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'image/jpeg', 
            'image/png', 
            'image/webp'
        ]

    def __call__(self, file):
        if file.size > self.max_size:
            raise ValidationError(f"File size exceeds the {self.max_size / 1024 / 1024}MB limit.")

        ext = os.path.splitext(file.name)[1].lower()
        if ext not in self.allowed_extensions:
            raise ValidationError(f"Unsupported file extension: {ext}. Allowed: {', '.join(self.allowed_extensions)}")

        # Optional strict MIME type checking could use python-magic, 
        # but relying on content_type and extension is a standard fallback
        if hasattr(file, 'content_type') and file.content_type not in self.allowed_mimetypes:
            raise ValidationError(f"Unsupported file MIME type: {file.content_type}.")
