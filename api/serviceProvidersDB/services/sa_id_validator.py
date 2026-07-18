from datetime import datetime


class SouthAfricanIDValidator:
    @staticmethod
    def validate(id_number: str):
        """
        Returns:
            {
                "valid": bool,
                "message": str,
                "dob": date,
                "gender": "Male"/"Female",
                "citizen": bool
            }
        """

        if not id_number:
            return {"valid": False, "message": "ID number is required."}

        id_number = str(id_number).strip()

        if not id_number.isdigit():
            return {"valid": False, "message": "ID number must contain only digits."}

        if len(id_number) != 13:
            return {"valid": False, "message": "South African ID must contain exactly 13 digits."}

        # ----------------------------
        # Date of birth
        # ----------------------------
        yy = int(id_number[0:2])
        mm = int(id_number[2:4])
        dd = int(id_number[4:6])

        current_year = datetime.now().year % 100

        if yy <= current_year:
            year = 2000 + yy
        else:
            year = 1900 + yy

        try:
            dob = datetime(year, mm, dd).date()
        except ValueError:
            return {
                "valid": False,
                "message": "Invalid date encoded in ID number."
            }

        # ----------------------------
        # Gender
        # ----------------------------
        gender_digits = int(id_number[6:10])

        gender = "Male" if gender_digits >= 5000 else "Female"

        # ----------------------------
        # Citizenship
        # ----------------------------
        citizen_digit = id_number[10]

        if citizen_digit not in ("0", "1"):
            return {
                "valid": False,
                "message": "Invalid citizenship digit."
            }

        citizen = citizen_digit == "0"

        # ----------------------------
        # Luhn checksum
        # ----------------------------
        if not SouthAfricanIDValidator._luhn(id_number):
            return {
                "valid": False,
                "message": "Invalid South African ID checksum."
            }

        return {
            "valid": True,
            "message": "Valid South African ID.",
            "dob": dob,
            "gender": gender,
            "citizen": citizen,
        }

    @staticmethod
    def _luhn(number: str) -> bool:
        total = 0
        reverse_digits = number[::-1]

        for i, char in enumerate(reverse_digits):
            digit = int(char)

            # Double every second digit, excluding the check digit
            if i % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9

            total += digit

        return total % 10 == 0