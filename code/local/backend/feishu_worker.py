"""Isolate the official SDK's synchronous WebSocket loop from FastAPI.

Credentials enter via stdin, events leave via stdout; never log credentials or WS URLs.
"""
import json
import logging
import sys


def emit(value):
    print(json.dumps(value, ensure_ascii=True), flush=True)


def main():
    import lark_oapi as lark

    if "--register" in sys.argv:
        try:
            result = lark.register_app(
                on_qr_code=lambda info: emit({"authorization_url": info["url"]}),
                app_preset={"name": "PaperTrail", "desc": "论文检索与大模型压缩每日推荐"},
                addons={"preset": False, "scopes": {"tenant": ["im:message:send_as_bot", "im:message.group_at_msg:readonly"]},
                        "events": {"items": {"tenant": ["im.message.receive_v1"]}}},
                create_only=False,
            )
        except Exception as exc:
            # Never emit exception messages: transports may include credentials in URLs.
            emit({"registration_error": type(exc).__name__})
            return
        emit({"credentials": {"app_id": result["client_id"], "app_secret": result["client_secret"]}})
        return

    config = json.loads(sys.stdin.readline())

    def receive(data):
        emit(json.loads(lark.JSON.marshal(data)))

    class ConnectionStatus(logging.Handler):
        def emit(self, record):
            message = record.getMessage()
            if "connected to" in message:
                emit({"status": "已连接"})
            elif "reconnect" in message or "receive message loop exit" in message:
                emit({"status": "正在重连"})
            elif record.levelno >= logging.ERROR:
                emit({"status": "连接异常，请检查飞书应用配置"})

    handler = lark.EventDispatcherHandler.builder("", "").register_p2_im_message_receive_v1(receive).build()
    client = lark.ws.Client(config["app_id"], config["app_secret"], event_handler=handler, log_level=lark.LogLevel.INFO)
    from lark_oapi.core.log import logger
    logger.handlers.clear()
    logger.addHandler(ConnectionStatus())
    logger.propagate = False
    client.start()


if __name__ == "__main__":
    main()
