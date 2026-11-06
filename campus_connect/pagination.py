from django.core.paginator import Paginator


def paginate(request, queryset, per_page=12):
    """Return (page, query_string) for list views.

    `page` is iterable like the queryset, so templates keep looping over it unchanged.
    Bad or out-of-range ?page= values fall back to the first/last page instead of erroring.
    `query_string` holds the other GET filters so the Prev/Next links keep them.
    """
    page = Paginator(queryset, per_page).get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    return page, params.urlencode()
