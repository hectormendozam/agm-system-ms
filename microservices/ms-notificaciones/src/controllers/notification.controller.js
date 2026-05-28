const emailService = require('../services/email.service');
const rpcClient = require('../clients/rpc_client');

class NotificationController {
    async handleRetardo(data) {
        try {
            console.log(`Procesando retardo para alumno ${data.alumno_id} en materia ${data.materia_id}`);

            let destEmail = process.env.ALERT_EMAIL;
            let nombreAlumno = `Alumno ID ${data.alumno_id}`;

            const response = await rpcClient.call('rpc_docentes_queue', 'get_alumno', { alumnoId: data.alumno_id });

            if (response && response.success && response.data) {
                destEmail = response.data.email || destEmail;
                nombreAlumno = response.data.nombre || nombreAlumno;
            }

            const mailOptions = {
                to: destEmail,
                subject: `Aviso de Retardo - Materia ${data.materia_id}`,
                html: `<p>Hola ${nombreAlumno},</p><p>Se ha registrado un retardo en tu asistencia el día ${data.timestamp}.</p><p>Saludos.</p>`
            };

            await emailService.sendMail(mailOptions, 'retardo', data.alumno_id);
        } catch (error) {
            console.error("Error al procesar notificación de retardo:", error);
        }
    }

    async handleBienvenida(data) {
        const { alumnoNombre, alumnoEmail, alumnoId, materiaNombre, claveUnica } = data;
        
        const mailOptions = {
            to: alumnoEmail,
            subject: `¡Bienvenido a la materia: ${materiaNombre}!`,
            html: `
                <h2>Hola ${alumnoNombre}</h2>
                <p>Tu registro en la materia <b>${materiaNombre}</b> ha sido exitoso.</p>
                <p>Tus credenciales de acceso al sistema AGM son:</p>
                <ul>
                    <li><b>Usuario:</b> ${alumnoEmail}</li>
                    <li><b>Contraseña:</b> ${claveUnica}</li>
                </ul>
                <p>Por favor, ingresa al portal para cambiar tu contraseña.</p>
            `
        };

        return await emailService.sendMail(mailOptions, 'bienvenida_alumno', alumnoId);
    }

    async handleBienvenidaDocente(data) {
        const { docenteNombre, docenteEmail, docenteId, claveUnica } = data;
        
        const mailOptions = {
            to: docenteEmail,
            subject: `¡Bienvenido al sistema AGM, Profesor(a) ${docenteNombre}!`,
            html: `
                <h2>Hola ${docenteNombre}</h2>
                <p>Se ha creado su cuenta como <b>Docente</b> en el sistema Academic Grade Management (AGM).</p>
                <p>Sus credenciales de acceso son:</p>
                <ul>
                    <li><b>Usuario:</b> ${docenteEmail}</li>
                    <li><b>Contraseña:</b> ${claveUnica}</li>
                </ul>
                <p>Le recomendamos cambiar su contraseña al iniciar sesión por primera vez.</p>
            `
        };

        return await emailService.sendMail(mailOptions, 'bienvenida_docente', docenteId);
    }

    async handleBaja(data) {
        const { alumnoNombre, docenteNombre, docenteEmail, docenteId } = data;

        const mailOptions = {
            to: docenteEmail,
            subject: `Aviso del Sistema: Baja de Alumno - ${alumnoNombre}`,
            html: `
                <h2>Hola Profesor(a) ${docenteNombre},</h2>
                <p>Le notificamos oficialmente que el alumno <b>${alumnoNombre}</b> ha procesado su baja de la materia.</p>
                <p>Este cambio ya se refleja en su concentrado de alumnos.</p>
            `
        };

        return await emailService.sendMail(mailOptions, 'baja', docenteId);
    }

    async handleCierreMateria(data) {
        const { materiaId, materiaNombre, alumnosEmails } = data;

        if (!alumnosEmails || alumnosEmails.length === 0) {
            console.log("-> Sin alumnos a notificar del cierre de materia.");
            return { success: true, message: "No recipients" };
        }

        const mailOptions = {
            to: process.env.MAIL_FROM_EMAIL, // Se envía al remitente como principal
            bccList: Array.isArray(alumnosEmails) ? alumnosEmails : [alumnosEmails],
            subject: `Aviso Académico: Cierre de la materia ${materiaNombre}`,
            html: `
                <h2>Aviso Importante</h2>
                <p>Estimado alumno, le notificamos que el docente ha cerrado oficialmente la evaluación para la materia: <b>${materiaNombre}</b>.</p>
                <p>Sus calificaciones finales ya han sido publicadas y no están sujetas a más modificaciones.</p>
                <p>Por favor, ingrese al sistema AGM para revisar su concentrado.</p>
            `
        };

        return await emailService.sendMail(mailOptions, 'cierre_materia', materiaId);
    }

    async handleResetPassword(data) {
        const { email, token } = data;
        const baseUrl = process.env.FRONTEND_URL;
        const resetUrl = `${baseUrl}/restablecer?token=${token}`;

        const mailOptions = {
            to: email,
            subject: `Recuperación de Contraseña - AGM`,
            html: `
                <h2>Recuperación de Acceso</h2>
                <p>Hemos recibido una solicitud para restablecer la contraseña de su cuenta.</p>
                <p>Haga clic en el siguiente enlace seguro para crear una nueva contraseña:</p>
                <a href="${resetUrl}" style="display: inline-block; padding: 10px 20px; background-color: #004b87; color: #ffffff; text-decoration: none; border-radius: 5px;">Restablecer Contraseña</a>
                <p><small>Este enlace es de un solo uso y expirará por seguridad. Si no solicitó este cambio, ignore este correo.</small></p>
            `
        };

        return await emailService.sendMail(mailOptions, 'reset_password', null);
    }
}

module.exports = new NotificationController();
