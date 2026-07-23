class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int = 400,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.detail = detail


class NotFoundError(AppError):
    def __init__(
        self,
        code: str = "not_found",
        message: str | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(
            code=code, message=message or code, status_code=404, detail=detail
        )


class ConflictError(AppError):
    def __init__(
        self,
        code: str = "conflict",
        message: str | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(
            code=code, message=message or code, status_code=409, detail=detail
        )


class ValidationError(AppError):
    def __init__(
        self,
        code: str = "validation_error",
        message: str | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(
            code=code, message=message or code, status_code=422, detail=detail
        )


class PermissionError(AppError):
    def __init__(
        self,
        code: str = "permission_denied",
        message: str | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(
            code=code, message=message or code, status_code=403, detail=detail
        )


class DependencyError(AppError):
    def __init__(
        self,
        code: str = "dependency_error",
        message: str | None = None,
        detail: dict | None = None,
    ) -> None:
        super().__init__(
            code=code, message=message or code, status_code=502, detail=detail
        )
