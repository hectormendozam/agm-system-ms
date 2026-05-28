const { brevoApi, smtpTransporter } = require('../config/mailer');
const db = require('../config/database');

class EmailService {
    /**
     * Envía un correo eligiendo automáticamente entre Brevo API o SMTP
     */
    async sendMail(options, notificationType, referenceId) {
        try {
            const mailFrom = process.env.MAIL_FROM || "AGM System <noreply@agm.com>";
            let result;

            // PRIORIDAD 1: Brevo API (Producción)
            if (brevoApi) {
                console.log(`[EmailService] Enviando ${notificationType} vía Brevo API...`);
                
                let sender = { email: mailFrom };
                const match = mailFrom.match(/(.*)<(.*)>/);
                if (match) {
                    sender.name = match[1].trim();
                    sender.email = match[2].trim();
                }

                const emailPayload = {
                    subject: options.subject,
                    htmlContent: options.html,
                    sender: sender,
                    to: (Array.isArray(options.to) ? options.to : [options.to]).map(email => ({ email }))
                };

                if (options.bccList) {
                    emailPayload.bcc = options.bccList.map(email => ({ email }));
                }

                const response = await brevoApi.transactionalEmails.sendTransacEmail(emailPayload);
                result = { success: true, messageId: response.data ? response.data.messageId : 'API-OK' };
            } 
            // PRIORIDAD 2: SMTP (Local / smtp4dev)
            else if (smtpTransporter) {
                console.log(`[EmailService] Enviando ${notificationType} vía SMTP (${options.to})...`);
                const mailOptions = {
                    from: mailFrom,
                    to: options.to,
                    subject: options.subject,
                    html: options.html,
                    bcc: options.bccList
                };

                const info = await smtpTransporter.sendMail(mailOptions);
                result = { success: true, messageId: info.messageId };
            } 
            else {
                throw new Error("No hay configurado ningún método de envío de correos (Brevo API o SMTP)");
            }

            console.log(`[EmailService] ÉXITO: Correo despachado. ID: ${result.messageId}`);
            await this.logHistory(notificationType, options.to || "BCC Group", referenceId, 'enviado');
            return result;

        } catch (error) {
            console.error(`[EmailService] Fallo enviando correo ${notificationType}:`, error.message);
            await this.logHistory(notificationType, options.to || "BCC Group", referenceId, 'fallido');
            throw error;
        }
    }

    async logHistory(type, recipient, referenceId, status) {
        try {
            const query = 'INSERT INTO historial_correos (tipo_notificacion, destinatario, referencia_id, estado) VALUES ($1, $2, $3, $4)';
            const values = [type, recipient, referenceId ? referenceId.toString() : null, status];
            await db.query(query, values);
        } catch (dbError) {
            console.error("[EmailService] Error en historial BD:", dbError.message);
        }
    }
}

module.exports = new EmailService();
