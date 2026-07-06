import logging
import smtplib
from pathlib import Path
from html import escape
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
import ssl

from fastapi import HTTPException

from app.core.config import settings

logger = logging.getLogger(__name__)

SUPPORT_EMAIL = "IncedoInternalSystems@incedoinc.com"

# Use domain-like CID. Outlook behaves better with this format.
LOGO_CID = "logo_intellihire@intellihire.local"


def get_logo_path() -> Path | None:
    """
    email_service.py location: app/services/email_service.py
    logo location: app/static/logo_intellihire.png
    """
    app_dir = Path(__file__).resolve().parents[1]
    logo_path = app_dir / "static" / "logo_intellihire.png"

    if logo_path.exists() and logo_path.is_file():
        return logo_path

    return None


def get_intellihire_logo_html() -> str:
    """
    Returns logo HTML.

    If PNG exists, uses CID inline image.
    If PNG is missing, returns text logo fallback so Outlook does not show broken image.
    """
    if get_logo_path():
        return f"""
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:0 0 24px 0;">
  <tr>
    <td style="vertical-align:middle;">
      <img
        src="cid:{LOGO_CID}"
        width="180"
        alt="IntelliHire"
        style="display:block;border:0;outline:none;text-decoration:none;width:180px;height:auto;"
      />
    </td>
  </tr>
</table>
"""

    return """
<table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:0 0 24px 0;">
  <tr>
    <td style="font-family:Arial,Helvetica,sans-serif;font-size:22px;font-weight:bold;line-height:24px;">
      <span style="color:#3B3FE8;">Intelli</span><span style="color:#00A651;">Hire</span>
    </td>
  </tr>
  <tr>
    <td style="font-family:Arial,Helvetica,sans-serif;font-size:10px;color:#667085;line-height:14px;">
      Speed Meets Precision
    </td>
  </tr>
</table>
"""




def send_email(
    to_email: str,
    subject: str,
    body: str,
    html_body: str | None = None,
) -> bool:
    try:
        message = MIMEMultipart("related")
        message["Subject"] = subject
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        message["To"] = to_email

        alternative_part = MIMEMultipart("alternative")
        alternative_part.attach(MIMEText(body, "plain", "utf-8"))

        if html_body:
            alternative_part.attach(MIMEText(html_body, "html", "utf-8"))

        message.attach(alternative_part)

        if html_body:
            logo_path = get_logo_path()

            if logo_path:
                with open(logo_path, "rb") as logo_file:
                    logo_part = MIMEImage(logo_file.read(), _subtype="png")

                logo_part.add_header("Content-ID", f"<{LOGO_CID}>")
                logo_part.add_header("X-Attachment-Id", LOGO_CID)
                logo_part.add_header(
                    "Content-Disposition",
                    "inline",
                    filename="intellihire_logo.png",
                )

                message.attach(logo_part)
            else:
                logger.warning(
                    "IntelliHire logo not found at app/static/intellihire_logo.png"
                )

        context = ssl.create_default_context()

        with smtplib.SMTP(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout,
        ) as server:
            server.ehlo()

            if not settings.smtp_use_tls:
                raise RuntimeError(
                    "SMTP_USE_TLS must be enabled for secure mail transmission"
                )

            if not server.has_extn("STARTTLS"):
                raise RuntimeError(
                    "SMTP server does not support STARTTLS"
                )

            server.starttls(context=context)
            server.ehlo()

            if settings.smtp_username and settings.smtp_password:
                server.login(
                    settings.smtp_username,
                    settings.smtp_password,
                )

            server.sendmail(
                settings.smtp_from_email,
                [to_email],
                message.as_string(),
            )

        logger.info("Email sent successfully to %s", to_email)
        return True

    except Exception as e:
        logger.exception("Failed to send email to %s: %s", to_email, e)
        return False

def send_interviewer_assessment_assigned_email(
    interviewer_email: str,
    interviewer_name: str,
    candidate_name: str,
    req_id: str,
    jd_title: str,
    interview_round: str,
    assessment_link: str,
):
    subject = f"Assessment Assigned - {candidate_name}"

    body = f"""
Hello {interviewer_name},

You have been assigned to assess the candidate below.

Candidate Name: {candidate_name}
Req ID: {req_id}
JD Title: {jd_title}
Interview Round: {interview_round}

To view details click here:
{assessment_link}

In case of any technical issue, please reach out to support team ({SUPPORT_EMAIL})

Thank you.

Regards,
IntelliHire Team

This is an auto generated email for your records & actions
"""

    safe_interviewer_name = escape(interviewer_name or "Interviewer")
    safe_candidate_name = escape(candidate_name or "-")
    safe_req_id = escape(req_id or "-")
    safe_jd_title = escape(jd_title or "-")
    safe_interview_round = escape(interview_round or "-")
    safe_assessment_link = escape(assessment_link or "#", quote=True)
    safe_support_email = escape(SUPPORT_EMAIL, quote=True)

    html_body = f"""
<!DOCTYPE html>
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;color:#111827;font-size:14px;line-height:1.5;margin:0;padding:24px;background-color:#ffffff;">

    {get_intellihire_logo_html()}

    <p style="margin:0 0 18px 0;">
      Hi <strong>{safe_interviewer_name}</strong>,
    </p>

    <p style="margin:0 0 18px 0;">
      You have been assigned to assess the candidate below. Please find the assessment details below:
    </p>

    <table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:0 0 28px 0;width:auto;">
      <tr>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Candidate Name</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Req ID</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">JD Title</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Interview Round</td>
      </tr>
      <tr>
        <td style="border:1px solid #000000;padding:8px;">{safe_candidate_name}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_req_id}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_jd_title}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_interview_round}</td>
      </tr>
    </table>
    <br>
    <p style="margin:0 0 20px 0;">
      To view details <a href="{safe_assessment_link}" style="color:#0000ee;text-decoration:underline;">click here</a>
    </p>


    <p style="margin:0 0 42px 0;">
      In case of any technical issue, please reach out to support team
      (<a href="mailto:{safe_support_email}" style="color:#0000ee;text-decoration:underline;">{safe_support_email}</a>)
    </p>

    
    <p style="margin:0;font-size:13px;font-style:italic;color:#111827;">
      This is an auto generated email for your records &amp; actions
    </p>

  </body>
</html>
"""

    send_email(
        to_email=interviewer_email,
        subject=subject,
        body=body,
        html_body=html_body,
    )


def send_assessment_completed_email(
    recruiter_email: str,
    recruiter_name: str,
    candidate_name: str,
    req_id: str,
    jd_title: str,
    round_name: str,
    interviewer_name: str,
    recommendation: str,
    assessment_link: str,
):
    subject = f"Assessment Completed - {candidate_name}"

    body = f"""
Hello {recruiter_name},

The assessment for the following candidate has been completed. You can review the assessment details and AI-generated summary using the link below.

Candidate Name: {candidate_name}
Req ID: {req_id}
JD Title: {jd_title}
Interview Round: {round_name}
Interviewer: {interviewer_name}
Assessment Status: Completed
Recommendation: {recommendation}

To view details click here:
{assessment_link}

In case of any technical issue, please reach out to support team ({SUPPORT_EMAIL})

Regards,
IntelliHire Team

This is an auto generated email for your records & actions
"""

    safe_recruiter_name = escape(recruiter_name or "Recruiter")
    safe_candidate_name = escape(candidate_name or "-")
    safe_req_id = escape(req_id or "-")
    safe_jd_title = escape(jd_title or "-")
    safe_round_name = escape(round_name or "-")
    safe_interviewer_name = escape(interviewer_name or "-")
    safe_recommendation = escape(recommendation or "-")
    safe_assessment_link = escape(assessment_link or "#", quote=True)
    safe_support_email = escape(SUPPORT_EMAIL, quote=True)

    html_body = f"""
<!DOCTYPE html>
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;color:#111827;font-size:14px;line-height:1.5;margin:0;padding:24px;background-color:#ffffff;">

    {get_intellihire_logo_html()}

    <p style="margin:0 0 18px 0;">
      Hi <strong>{safe_recruiter_name}</strong>,
    </p>

    <p style="margin:0 0 18px 0;">
      The assessment for the following candidate has been completed. You can review the assessment details and AI-generated summary using the link below.
    </p>

    <p style="margin:0 0 14px 0;">
      Please find the assessment details below:
    </p>

    <table cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin:0 0 28px 0;width:auto;">
      <tr>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Candidate Name</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Req ID</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">JD Title</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Interview Round</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Interviewer</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Assessment Status</td>
        <td style="border:1px solid #000000;background-color:#f2f2f2;padding:8px;font-weight:bold;">Recommendation</td>
      </tr>
      <tr>
        <td style="border:1px solid #000000;padding:8px;">{safe_candidate_name}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_req_id}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_jd_title}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_round_name}</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_interviewer_name}</td>
        <td style="border:1px solid #000000;padding:8px;">Completed</td>
        <td style="border:1px solid #000000;padding:8px;">{safe_recommendation}</td>
      </tr>
    </table>

    <br>

    <p style="margin:0 0 20px 0;">
      To view details <a href="{safe_assessment_link}" style="color:#0000ee;text-decoration:underline;">click here</a>
    </p>


    
    <p style="margin:0 0 42px 0;">
      In case of any technical issue, please reach out to support team
      (<a href="mailto:{safe_support_email}" style="color:#0000ee;text-decoration:underline;">{safe_support_email}</a>)
    </p>


    <p style="margin:0 0 38px 0;">
      Regards,<br/>
      IntelliHire Team
    </p>

    <p style="margin:0;font-size:13px;font-style:italic;color:#111827;">
      This is an auto generated email for your records &amp; actions
    </p>

  </body>
</html>
"""

    send_email(
        to_email=recruiter_email,
        subject=subject,
        body=body,
        html_body=html_body,
    )

def send_assessment_submission_confirmation_email(
    interviewer_email: str,
    interviewer_name: str,
    candidate_name: str,
    round_name: str,
    recommendation: str,
) -> bool:
    try:
        subject = f"Assessment Submitted Successfully - {candidate_name or '-'}"

        body = f"""
Hi {interviewer_name or 'Interviewer'},

Your assessment has been submitted successfully.

Candidate: {candidate_name or '-'}
Round: {round_name or '-'}
Recommendation: {recommendation or '-'}

Regards,
IntelliHire
"""

        safe_interviewer_name = escape(interviewer_name or "Interviewer")
        safe_candidate_name = escape(candidate_name or "-")
        safe_round_name = escape(round_name or "-")
        safe_recommendation = escape(recommendation or "-")

        html_body = f"""
<!DOCTYPE html>
<html>
  <body style="font-family:Arial,Helvetica,sans-serif;color:#344054;font-size:14px;line-height:1.5;margin:0;padding:24px;background-color:#ffffff;">

    {get_intellihire_logo_html()}

    <p style="margin:0 0 18px 0;">
      Hi <strong>{safe_interviewer_name}</strong>,
    </p>

    <p style="margin:0 0 18px 0;">
      Your assessment has been submitted successfully.
    </p>

    <table cellpadding="8" cellspacing="0" border="0" style="border-collapse:collapse;border:1px solid #EAECF0;margin-top:16px;margin-bottom:16px;">
      <tr>
        <td style="border:1px solid #EAECF0;"><strong>Candidate</strong></td>
        <td style="border:1px solid #EAECF0;">{safe_candidate_name}</td>
      </tr>
      <tr>
        <td style="border:1px solid #EAECF0;"><strong>Round</strong></td>
        <td style="border:1px solid #EAECF0;">{safe_round_name}</td>
      </tr>
      <tr>
        <td style="border:1px solid #EAECF0;"><strong>Recommendation</strong></td>
        <td style="border:1px solid #EAECF0;">{safe_recommendation}</td>
      </tr>
    </table>

    <p style="margin:0 0 18px 0;">
      Thank you for completing the assessment.
    </p>

    <p style="margin:0;">
      Regards,<br/>
      IntelliHire
    </p>

  </body>
</html>
"""

        email_sent = send_email(
            to_email=interviewer_email,
            subject=subject,
            body=body,
            html_body=html_body,
        )

        if not email_sent:
            raise RuntimeError(
                f"Failed to send assessment submission confirmation email to {interviewer_email}"
            )

        logger.info(
            "Assessment submission confirmation email sent successfully. interviewer_email=%s, candidate_name=%s",
            interviewer_email,
            candidate_name,
        )

        return True

    except Exception as e:
        logger.exception(
            "Failed to send assessment submission confirmation email. interviewer_email=%s, candidate_name=%s, error=%s",
            interviewer_email,
            candidate_name,
            e,
        )
        raise

def send_email_or_raise(email_func, **kwargs):
    try:
        email_func(**kwargs)
    except Exception as e:
        logger.exception("Failed to send email using %s: %s", email_func.__name__, str(e))
        raise HTTPException(
            status_code=500,
            detail="Failed to send email notification.",
        )