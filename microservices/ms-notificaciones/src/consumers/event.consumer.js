const amqp = require('amqplib');
const authService = require('../services/auth.service');
const notificationController = require('../controllers/notification.controller');

class EventConsumer {
    constructor() {
        this.rabbitUrl = process.env.RABBITMQ_URL || 'amqp://localhost';
        this.exchange = 'events_exchange';
        this.queue = 'notifications_queue';
        this.routingKeys = [
            'auth.reset_password',
            'periodos.materia_cerrada',
            'periodos.bienvenida',
            'docentes.bienvenida',
            'docentes.baja',
            'asistencias.retardo'
        ];
        this.connection = null;
    }

    async start() {
        try {
            console.log('[EventConsumer] Connecting to RabbitMQ...');
            this.connection = await amqp.connect(this.rabbitUrl);
            const channel = await this.connection.createChannel();

            this.connection.on('error', (err) => {
                console.error('[EventConsumer] Connection error:', err.message);
            });

            this.connection.on('close', () => {
                console.log('[EventConsumer] Connection closed. Reconnecting...');
                setTimeout(() => this.start(), 5000);
            });

            await channel.assertExchange(this.exchange, 'topic', { durable: true });
            await channel.assertQueue(this.queue, { durable: true });

            for (const key of this.routingKeys) {
                await channel.bindQueue(this.queue, this.exchange, key);
            }

            console.log(`[RabbitMQ] Consumidor de Notificaciones listo. Cola: ${this.queue}`);

            channel.consume(this.queue, async (msg) => {
                if (!msg) return;
                
                const routingKey = msg.fields.routingKey;
                const deliveryTag = msg.fields.deliveryTag;
                console.log(`[RabbitMQ] Recibido evento: ${routingKey} (Tag: ${deliveryTag})`);

                try {
                    const content = JSON.parse(msg.content.toString());
                    
                    // Middleware de Autenticación
                    if (routingKey !== 'auth.reset_password' && routingKey !== 'asistencias.retardo') {
                        console.log(`[RabbitMQ] Validando token para ${routingKey}...`);
                        const authResult = await authService.validateToken(content.auth_token);
                        
                        if (!authResult || !authResult.valid) {
                            console.warn(`[RabbitMQ] Evento ${routingKey} (Tag: ${deliveryTag}) RECHAZADO: Token inválido.`);
                            return channel.ack(msg);
                        }
                        console.log(`[RabbitMQ] Evento ${routingKey} AUTENTICADO.`);
                    }

                    // Enrutamiento
                    switch (routingKey) {
                        case 'periodos.bienvenida':
                            await notificationController.handleBienvenida(content);
                            break;
                        case 'docentes.bienvenida':
                            await notificationController.handleBienvenidaDocente(content);
                            break;
                        case 'docentes.baja':
                            await notificationController.handleBaja(content);
                            break;
                        case 'periodos.materia_cerrada':
                            await notificationController.handleCierreMateria(content);
                            break;
                        case 'auth.reset_password':
                            await notificationController.handleResetPassword(content);
                            break;
                        case 'asistencias.retardo':
                            await notificationController.handleRetardo(content);
                            break;
                        default:
                            console.warn(`[RabbitMQ] Evento desconocido: ${routingKey}`);
                    }
                    
                    console.log(`[RabbitMQ] Procesamiento exitoso. Enviando ACK para tag ${deliveryTag}`);
                    channel.ack(msg);
                } catch (error) {
                    console.error(`[RabbitMQ] Error procesando evento ${routingKey}:`, error.message);
                    try {
                        console.log(`[RabbitMQ] Enviando ACK de error para tag ${deliveryTag}`);
                        channel.ack(msg);
                    } catch (ackError) {
                        console.error(`[RabbitMQ] Fallo al enviar ACK de error: ${ackError.message}`);
                    }
                }
            }, { noAck: false });
        } catch (error) {
            console.error("[RabbitMQ] Fallo al iniciar consumidor:", error.message);
            setTimeout(() => this.start(), 5000);
        }
    }
}

module.exports = new EventConsumer();
