import logging

from django.conf import settings
from django.core.management.base import BaseCommand
from huggingface_hub import InferenceClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Fetch a response from Qwen2.5-Coder-32B-Instruct model using a user query'

    def add_arguments(self, parser):
        """Register the `query` positional argument for the command."""
        parser.add_argument('query', type=str, help='The query to be processed by the model')

    def handle(self, *args, **kwargs):
        """Handle the query and log the response from the Qwen2.5-Coder-32B-Instruct model."""
        query = kwargs['query']

        # Initialize the InferenceClient with the Qwen2.5-Coder-32B-Instruct model
        client = InferenceClient(
            # "Qwen/Qwen2.5-Coder-32B-Instruct",
            # 'meta-llama/Llama-3.1-8B-Instruct',
            # 'openai-community/gpt2',
            'mistralai/Mixtral-8x7B-Instruct-v0.1',
            token=settings.HUGGING_FACE_API,
        )

        # Fetch the model's response
        try:
            response = client.text_generation(query)
            logger.info(f'Model Response: {response}')
        except Exception as e:
            logger.error(f'Error while querying the model: {e}')
