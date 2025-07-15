#!/usr/bin/env python3
"""
Examples of using structured outputs with Simon Willison's LLM library via Python API.

This file demonstrates various ways to get structured JSON output from LLMs using
the llm library's Python API.

Requirements:
    pip install llm
    # Configure your API key:
    llm keys set openai  # or set OPENAI_API_KEY environment variable
"""

import json
from typing import List, Optional

import llm
from pydantic import BaseModel, Field


# Example 1: Using Pydantic models for schemas
class Dog(BaseModel):
    """A simple dog model"""

    name: str = Field(description="The dog's name")
    age: int = Field(description="The dog's age in years")
    breed: str = Field(description="The breed of the dog")
    bio: str = Field(description="A brief biography of the dog")


class DogList(BaseModel):
    """A list of dogs"""

    dogs: List[Dog] = Field(description="List of dogs")


# Example 2: Using dictionary schemas (JSON Schema format)
person_schema = {
    "type": "object",
    "properties": {
        "name": {"type": "string", "description": "The person's full name"},
        "age": {"type": "integer", "description": "The person's age"},
        "occupation": {"type": "string", "description": "The person's job or profession"},
        "hobbies": {"type": "array", "items": {"type": "string"}, "description": "List of hobbies"},
    },
    "required": ["name", "age", "occupation"],
}


# Example 3: Using the concise DSL syntax
def example_dsl_syntax():
    """Demonstrate LLM's concise schema DSL syntax"""
    model = llm.get_model("gpt-4o-mini")

    # Simple schema using DSL
    response = model.prompt(
        "Describe a software engineer",
        schema=llm.schema_dsl("name, age int, programming_languages, years_experience int"),
    )
    print("DSL Schema Result:")
    print(json.dumps(json.loads(response.text()), indent=2))

    # Multi-item schema using DSL
    response = model.prompt(
        "List 3 popular programming languages",
        schema=llm.schema_dsl("name, year_created int, creator, main_use_case", multi=True),
    )
    print("\nDSL Multi Schema Result:")
    print(json.dumps(json.loads(response.text()), indent=2))


def example_pydantic_schema():
    """Demonstrate using Pydantic models for schemas"""
    model = llm.get_model("gpt-4o-mini")

    # Single dog
    response = model.prompt("Describe a heroic rescue dog", schema=Dog)
    dog_data = json.loads(response.text())
    print("\nPydantic Schema Result (Single Dog):")
    print(json.dumps(dog_data, indent=2))

    # Multiple dogs using a list schema
    response = model.prompt("Describe 3 famous dogs from movies or TV", schema=DogList)
    dogs_data = json.loads(response.text())
    print("\nPydantic Schema Result (Multiple Dogs):")
    print(json.dumps(dogs_data, indent=2))


def example_dict_schema():
    """Demonstrate using dictionary schemas"""
    model = llm.get_model("gpt-4o-mini")

    response = model.prompt("Describe a famous scientist", schema=person_schema)
    person_data = json.loads(response.text())
    print("\nDictionary Schema Result:")
    print(json.dumps(person_data, indent=2))


def example_nested_schema():
    """Demonstrate more complex nested schemas"""

    # Define a complex nested schema
    class Address(BaseModel):
        street: str
        city: str
        country: str
        postal_code: Optional[str] = None

    class Company(BaseModel):
        name: str
        industry: str
        founded_year: int
        headquarters: Address
        employee_count: Optional[int] = None

    class TechCompanies(BaseModel):
        companies: List[Company]

    model = llm.get_model("gpt-4o-mini")

    response = model.prompt("List 2 major tech companies with their headquarters information", schema=TechCompanies)

    companies_data = json.loads(response.text())
    print("\nNested Schema Result:")
    print(json.dumps(companies_data, indent=2))


def example_extraction_from_text():
    """Demonstrate extracting structured data from unstructured text"""

    # Schema for extracting meeting information
    class Meeting(BaseModel):
        title: str = Field(description="Meeting title or subject")
        date: str = Field(description="Date in YYYY-MM-DD format")
        time: str = Field(description="Time in HH:MM format")
        attendees: List[str] = Field(description="List of attendee names")
        key_topics: List[str] = Field(description="Main topics discussed")
        action_items: List[str] = Field(description="Action items or next steps")

    # Sample unstructured text
    meeting_notes = """
    Team Standup - March 15, 2024 at 10:30 AM

    Present: Alice Johnson, Bob Smith, Carol Davis, David Lee

    We discussed the upcoming product launch and reviewed the current sprint progress.
    Alice presented the new UI designs which everyone approved. Bob mentioned that
    the backend API is 80% complete. Carol raised concerns about the testing timeline.

    Action items:
    - Alice to finalize UI mockups by Friday
    - Bob to complete API documentation
    - Carol to create comprehensive test plan
    - David to schedule stakeholder review for next week
    """

    model = llm.get_model("gpt-4o-mini")

    response = model.prompt(f"Extract meeting information from these notes:\n\n{meeting_notes}", schema=Meeting)

    meeting_data = json.loads(response.text())
    print("\nExtracted Meeting Information:")
    print(json.dumps(meeting_data, indent=2))


def example_with_system_prompt():
    """Demonstrate using schemas with system prompts"""

    class Recipe(BaseModel):
        name: str
        cuisine: str
        prep_time_minutes: int
        cooking_time_minutes: int
        servings: int
        ingredients: List[str]
        instructions: List[str]
        difficulty: str = Field(description="Easy, Medium, or Hard")

    model = llm.get_model("gpt-4o-mini")

    response = model.prompt(
        "Give me a recipe for a quick weeknight dinner",
        schema=Recipe,
        system="You are a professional chef specializing in healthy, quick meals. "
        "Focus on recipes that use common ingredients and can be made in under 30 minutes total.",
    )

    recipe_data = json.loads(response.text())
    print("\nRecipe with System Prompt:")
    print(json.dumps(recipe_data, indent=2))


def example_response_json_property():
    """Demonstrate accessing the response_json property"""
    model = llm.get_model("gpt-4o-mini")

    response = model.prompt("Describe a cat", schema=llm.schema_dsl("name, age int, color, personality_trait"))

    # The response object has a response_json property
    print("\nDirect access to response_json:")
    print(json.dumps(response.json(), indent=2))


def example_error_handling():
    """Demonstrate error handling with schemas"""
    model = llm.get_model("gpt-4o-mini")

    # Check if model supports schemas
    if not getattr(model, "supports_schema", True):
        print("This model does not support schemas")
        return

    try:
        # This should work
        response = model.prompt(
            "Generate a number", schema={"type": "object", "properties": {"number": {"type": "integer"}}}
        )
        print("\nSuccessful schema response:")
        print(response.text())

    except Exception as e:
        print(f"Error: {e}")


def main():
    """Run all examples"""
    print("=== LLM Structured Output Examples ===\n")

    # Make sure we have a valid model
    try:
        model = llm.get_model("gpt-4o-mini")
    except llm.UnknownModelError:
        print("Error: gpt-4o-mini model not available")
        print("Available models:")
        for model_id in llm.models():
            print(f"  - {model_id}")
        return

    # Run examples
    print("\n--- Example 1: DSL Syntax ---")
    example_dsl_syntax()

    print("\n--- Example 2: Pydantic Schema ---")
    example_pydantic_schema()

    print("\n--- Example 3: Dictionary Schema ---")
    example_dict_schema()

    print("\n--- Example 4: Nested Schema ---")
    example_nested_schema()

    print("\n--- Example 5: Extraction from Text ---")
    example_extraction_from_text()

    print("\n--- Example 6: With System Prompt ---")
    example_with_system_prompt()

    print("\n--- Example 7: Response JSON Property ---")
    example_response_json_property()

    print("\n--- Example 8: Error Handling ---")
    example_error_handling()


if __name__ == "__main__":
    main()
