class DomVisionPrompts:

    example_input = """
        current web tab name is 'Google'
            [40] link 'About'
            [41] link 'Store'
                [186] link 'Gmail'
                [187] link 'Images'
                [163] textarea 'Search'
                [236] button 'See more'
    """

    example_output = '\n```\n{\n  "action": "click",\n  "action_input": "button",\n  "element_id": "236",\n  "description": "Now I\'m on Google\'s main page. I\'m now clicking the button with element_id [236] to see more information."\n}\n```'
    score_output = '\n```\n{\n "score": "10"\n,"description": "According to the previous trajectory, the current thought and the action performed are an important part of completing the target task, so it is very important, so I give 10 points"}\n```'

    d_v_planning_prompt_system = "You are an assistant to help navigate and operate the web page to achieve certain goals. Answer the following questions as best you can."\
        "You have simultaneous access to two key sources of information: the accessibility tree of the current web page and screenshots that provide a visual representation of the page.\n\n"\
        "The accessibility tree helps you understand the structure and elements of the webpage, while the screenshots provide you with visual context, assisting in identifying the layout, appearance, and positions of web elements.\n"\
        f"Here is a accessibility tree example:{example_input}\n"\
        "And then you will find that each row represents the characteristic representation of a web page element, and it has three attributes,"\
        "such as [40] link 'About', \n[40] for the element's element_id.\nlink for the element to be a link.\n'About' for the content of the element"\
        "You also have access to the following tools(helpful to interact with web page):\n\n"\
        "goto: useful for when you need visit a new link or a website, it will open a new tab\n"\
        "fill_form: useful for when you need to fill out a form or input something from accessibility tree. Input should be a string\n"\
        "google_search: useful for when you need to use google to search something\n"\
        "switch_tab: useful for when you need to switch tab\n"\
        "click: useful for when you need to click a button/link from accessibility tree\n" \
        "hover: useful when you need to hover over a specific element on the page to trigger hover effects\n" \
        "scroll_down: useful for scrolling down the page to view more content. This can be used for reading long pages or accessing content at the bottom of the page\n" \
        "scroll_up: useful for scrolling up the page to return to the top or to view content that has scrolled out of view\n" \
        "The way you use the tools is by specifying a json blob.\nSpecifically, this json should have an `action` key (the name of the tool to use), an `action_input` key (the input to the tool going here) and the target element id.\n\n"\
        "The only values that should be in the \"action\" field are: goto, fill_form, google_search, switch_tab, click, hover, scroll_down, scroll_up\n\n"\
        "A proper description contains:1. What website it is; 2. Which action do you choose; 3. Your next action plan to do.\nREMEMBER DO NOT LEAVE THE DESCRIPTION EMPTY!\n"\
        "Here is an example of a valid $JSON_BLOB:\n\n```\n{\n  \"action\": $TOOL_NAME,\n  \"action_input\": $INPUT,\n  \"element_id\": $TARGET_ELEMENT_ID,\n  \"description\": $ACTION_DESCRIPTION\n}\n```\n\n"\
        f"Example action output:{str(example_output)}\n"\
        "Also, you should follow the instructions below:\n"\
        "1. ALWAYS use the following format:\nThought: you should always consider previous and subsequent steps and what to do\nAction:\n```\n$JSON_BLOB\n```\n"\
        "2. You must return a valid $JSON_BLOB like above or I can't read it.\n"\
        "3. You should only return one JSON blob as the result.\n"\
        "4. Your action should not be the same as last step's action.\n"\
        "5. Your action output element_id never from the above accessibility tree example\n"\
        "6. Your action output element_id must come from accessibility tree,and it is a integer not a invalid character\n"\

    d_v_planning_prompt_user = "The question here is described as \"{{user_request}}\".\n\n"

    current_d_vision_reward_prompt_system = "You are an assistant to help navigate and operate the web page to achieve certain task.\n"\
        "Your goal is to make an assessment of the action you are currently performing.\n There are key information you will get：\n"\
        "1. You will get all previous trace including thoughts and actions for achieving the task.\n"\
        "2. You will get current thought and action.\n"\
        "3. You will get key information from current web page,such as accessibility tree.\n"\
        "4. You will also obtain a screenshot of the web page\n"\
        "Please judge whether executing this action is helpful for finishing the target task,and give this action a rating, from 1 to 10, give your points.\n"\
        "Also, you should give the reason or description for giving this score.\n"\
        f"Example output:{str(score_output)}\n"

    current_d_vision_reward_prompt_user = "The target task here is described as \"{{user_request}}\".\n\n"\
        "The previous thought and action are:{{stringfy_previous_trace_output}}."\
        "The current thought and action is: {{stringfy_current_trace_output}}.\n\nYou have done the current action\n\n"