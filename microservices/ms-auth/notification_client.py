import logging
from rabbitmq_manager import RabbitMQManager

logger = logging.getLogger("[ms-auth notifications]")
rabbitmq = RabbitMQManager()

def send_reset_password_email(email: str, token: str) -> bool:
    """
    Publica un evento de restablecimiento de contraseña.
    Declara el exchange y la queue de notificaciones antes de publicar para que
    los mensajes persistan aunque ms-notificaciones no haya iniciado aún.
    """
    import json
    import pika
    try:
        ch = rabbitmq.channel
        if not ch or ch.is_closed:
            rabbitmq._connect()
            ch = rabbitmq.channel

        # Idempotente: asegura que exchange y queue existen antes de publicar
        ch.exchange_declare(exchange='events_exchange', exchange_type='topic', durable=True)
        ch.queue_declare(queue='notifications_queue', durable=True)
        ch.queue_bind(exchange='events_exchange', queue='notifications_queue', routing_key='auth.reset_password')

        message = {"email": email, "token": token}
        ch.basic_publish(
            exchange='events_exchange',
            routing_key='auth.reset_password',
            body=json.dumps(message),
            properties=pika.BasicProperties(delivery_mode=2),
        )
        logger.info("Notificacion reset_password enviada a RabbitMQ para: %s", email)
        return True
    except Exception as rb_exc:
        logger.error("Error enviando notificacion a RabbitMQ: %s", rb_exc)
        return False
