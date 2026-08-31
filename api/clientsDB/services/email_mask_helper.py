
def mask_email(email):
    """
    Example:
    thando.tshabalala@gmail.com
    -> tha*********@gmail.com

    t.ptshabalala@gmail.com
    -> t.p*********@gmail.com
    """

    if not email or "@" not in email:
        return email

    local_part, domain = email.split("@", 1)

    # Keep the first 3 characters visible
    # and mask the remainder.
    if len(local_part) <= 3:
        masked_local = local_part[0] + "***"
    else:
        masked_local = local_part[:3] + "***"

    return f"{masked_local}@{domain}"

