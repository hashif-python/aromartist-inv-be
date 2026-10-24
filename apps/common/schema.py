def canonical_only(endpoints):
    return [entry for entry in endpoints if entry[0].startswith('/api/v1/')]
