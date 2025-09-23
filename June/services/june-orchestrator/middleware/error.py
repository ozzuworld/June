import logging
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

logger = logging.getLogger("api")


async def unhandled_errors(request: Request, call_next):
    try:
        response = await call_next(request)
        return response
    except HTTPException as e:
        # Expected errors: re-raise to let FastAPI make the proper response
        raise
    except Exception as e:
        logger.exception("unhandled_error")
        return JSONResponse(
            status_code=500,
            content={"ok": False, "error": "internal_error", "message": "Unexpected error"},
        )
