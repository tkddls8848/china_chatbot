class AppError(Exception):
    pass


class DataFetchError(AppError):
    pass


class NotFoundError(AppError):
    pass
