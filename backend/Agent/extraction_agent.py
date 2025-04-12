from dotenv import load_dotenv
from pydantic_ai import Agent
from models import Rubric , Question
from dotenv import load_dotenv
load_dotenv()
class RubricExtractionAgent:
    def __init__(self, model: str = "groq:qwen-qwq-32b"):
        """
        Initialize the agent with the specified Groq model.
        """
        self.agent = Agent(
            model=model,
            result_type=Rubric,
            system_prompt=(
                "You are an AI assistant that extracts questions and their corresponding marks "
                "from a given text. Return the data as a list of questions with their marks."
            )
        )

    def extract(self, input_text: str) -> dict:
        """
        Extract questions and marks from the input text.
        """
        result = self.agent.run_sync(input_text)
        return result.data.model_dump()
    
if __name__ == "__main__":
    # Sample input text containing questions and marks
    input_text = """
    1. Define edge computing. (2 marks)
    2. Differentiate between edge and cloud computing with examples. (5 marks)
    3. List any three edge computing platforms. (3 marks)
    """

    # Initialize the agent
    extractor = RubricExtractionAgent()

    # Extract the rubric
    rubric = extractor.extract(input_text)

    # Print the extracted rubric
    print(rubric)
