const nodemailer = require('nodemailer');
const { BrevoClient } = require('@getbrevo/brevo');
const path = require('path');
require('dotenv').config({ path: path.resolve(__dirname, '../../.env') });

// Opción 1: Cliente API de Brevo
let brevoApi = null;
if (process.env.BREVO_API_KEY) {
    console.log("[Mailer] Inicializando Brevo API Client...");
    brevoApi = new BrevoClient({
        apiKey: process.env.BREVO_API_KEY
    });
} else {
    console.log("[Mailer] BREVO_API_KEY no detectada.");
}

// Opción 2: Transporter SMTP (Nodemailer)
let smtpTransporter = null;
if (process.env.SMTP_HOST) {
    console.log(`[Mailer] Inicializando SMTP Transporter (${process.env.SMTP_HOST})...`);
    smtpTransporter = nodemailer.createTransport({
        host: process.env.SMTP_HOST,
        port: parseInt(process.env.SMTP_PORT || '25'),
        secure: false,
        tls: {
            rejectUnauthorized: false
        }
    });
}

module.exports = {
    brevoApi,
    smtpTransporter
};
