from django.contrib import messages
from django.shortcuts import redirect

from .storage import StorageUnavailable


class StorageErrorMiddleware:
    """Turn a failed file upload into a friendly message instead of a crashed request.

    Any view that saves a file can hit a storage outage; rather than guard each one, this
    sends the user back to the same page with an explanation (the file must be re-chosen).
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, StorageUnavailable) and request.method == 'POST':
            messages.error(request, 'We could not save your file right now. Please try again in a moment.')
            return redirect(request.path)
        return None
