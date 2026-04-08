import json
import logging
from google import genai
from django.conf import settings
from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView

logger = logging.getLogger(__name__)
client = genai.Client(api_key=settings.GEMINI_API_KEY)

class AIGenerateUnitsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        answers = request.data.get('answers', {})
        extra_notes = request.data.get('extra_notes', '')

        prompt = f"""
                    You are helping a property manager bulk-create rental units.
                    Generate a JSON array of exactly {answers.get('unitCount')} unit objects.
                    Extra context from the property manager (use to override defaults where relevant, ignore if unrelated): {extra_notes or 'None'}

                    Naming scheme: {answers.get('namingScheme')}
                    Monthly rent (KES): {answers.get('rent')}
                    Extra notes: {extra_notes or 'None'}

                    Return ONLY a valid JSON array. No explanation, no markdown, no code fences.
                    Each object must have exactly these fields:
                    {{
                    "code": string,       // unit identifier following the naming scheme e.g. "101", "A1", "Room 3"
                    "rooms": integer,     // infer from notes if mentioned, otherwise default to 1
                    "price": number,      // monthly rent in KES as a number
                    "condition": string,  // one of: excellent, good, fair, needs_repair, uninhabitable — default to "good"
                    "is_available": true // or False depending on the context provided perhaps in the extra notes attached
                    }}
                """

        try:
            response = client.models.generate_content(
                model='gemini-2.0-flash-lite',
                contents=prompt,
            )
            raw = response.text.strip()
            logger.debug('Gemini raw response: %s', raw)

            if raw.startswith('```'):
                raw = raw.split('\n', 1)[1]
                raw = raw.rsplit('```', 1)[0]

            units = json.loads(raw)
            if not isinstance(units, list):
                raise ValueError(f'Expected a list, got {type(units).__name__}')

        except json.JSONDecodeError as e:
            logger.error('Gemini JSON parse error: %s | raw: %s', e, raw)
            return Response(
                {'detail': 'Failed to parse AI response. Please try again.'},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except ValueError as e:
            logger.error('Gemini value error: %s', e)
            return Response(
                {'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        except Exception as e:
            logger.exception('Gemini API call failed: %s', e)
            return Response(
                {'detail': str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return Response({'units': units})