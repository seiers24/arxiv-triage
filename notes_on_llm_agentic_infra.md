# Building Effective Agents notes


## Prompt Chaining
Decompasing one task into a sequence of steps.  Like breaking a math problem down into building blocks.  Each LLM call processes the output of the previous one.  Programmatic checks should be implemented at intermediate steps to avoid drift.

Ideal for sitautions where task can be cleanly broken into fixed subtasks.  Trade latency for higher accuracy - this is done by making each LLM call an easier task.

For example: writing a document outline -> checking outline against certain criteria -> writing document based on outline

### How it relates to Arxiv-triage
We can utilize prompt chaining to break down arxiv proccessing into steps

pull arxiv paper via tool, convert to .json -> look for and extract features/advancements relative to a given subfield -> rank the paper based on novelty, and relatability to given subfield

### How it relates to past projects
This actually relates directly to Gemscan.  I utilized prompt chaining as follows:

First, extract features from image or text based on criterion(criterion goes here)
Then, utilizing those features as input, perform classification as to whether or not the text/image is scam, or safe.  Provide justification based on the features.

## Routing
Classifying an input and directing it to a followup task.  This works well for complex tasks with distinct categories that are best handled separately, where classification can be handled accurately.  

### How it relates to Arxiv-triage
If arxiv agent cannot determine whether a given paper relates well to a field, we might route that task to a different agent whose only job is to check the paper against the field, byte-by-byte.

If critic agent decides that it is not sure of a specific critique or portion of a paper, that task can be routed to a different agent.

## Parallelization

Having agents work simulatenously on a task and have their outputs aggregated programmatically.  Sectioning can break a task into independent subtasks and run in parallel.  Voting can mean running the same task multiple times to get diverse outputs

This is a lot like self-consistency, or best-of-n, where a prompt is ran many times by different agents and the best output is chosen based on a specific criterion.  More latency, but higher accuracy.  

### How it relates to Arix-triage
We can use sectioning for example when an arxiv paper crosses into multiple domains or sub-concepts, and have multiple critic agents, one for each domain or sub concept.  

We can also use voting to spawn multiple critic agents, have each critic agent take in the arxiv agents output schema as input, and develop multiple decisions based on that input, with the orchestrator judging the critics output or a "critic orchestrator" judging the critics.  

### How it relates to past projects
I actually frequently utilize parallelization on complex prompts I know I want maximum accuracy for.  For example, when it comes to research proposals.  When I am doing a literature survey of any kind in order to create a research proposal, I utilize multiple agents to do so.  Typically I use 1 agent per paper, as context per paper will change significantly.  Then I use an orchestrator to verify and validate individual agents findings.  

## Orchestrator-workers
A central LLM breaks down tasks dynamically and delegates to worker LLMs, synthesizing results.  
This works well for complex tasks where # of subtasks needed cannot be predicted.  This is a more flexible design as opposed to parallelization, as subtasks are determined by orchestrator.

### How it relates to Arxiv-triage
We actually already are implementing an orchestrator-worker design, where the orchestrator agent delegates to an arxiv reader agent to fetch, read, and extract important data from pre-print papers, and a critic to argue with the reader on whether or not the important data is actually important, or to put it more directly, whether or not the paper is directly relevant to anything that Micron cares about.  

This could also be paired with parallelism.  An orchestrator looks at a critics output, deems that there needs to be more critique done, and it spawns multiple critic agents to do the job.

### How it relates to past-projects
Just like parallelization, I use this every day.  Every single prompt I write for the most part, consists of an orchestrator with subagents.  The orchestrator tasks in the role, context, task, and output instructions.  It then delegates to worker agents to complete the tasks, for example that task might be to research a specific topic like diffusion for LLMs.  The orchestrator then verifies worker agent findings and creates an output document according to my instructions.  

## Evaluator-Optimzer
One LLM call generates a response while another provides eval and feedback in one single loop.  Input -> LLM Generator <-> LLM Evaluator -> Output

Clear evaluation criteria is required for this workflow, combined with potential for iterative refinement.  If LLM responses can be demonstrably improved when a human articulates their feedback, or when the LLM can provide such feedback, then this is a good option.  

Good for complex search tasks requiring multiple rounds of searching and analysis.  
### How it relates to Arxiv-triage
We are actually intending to directly implement this evaluator-optimizer workflow as it stands.  We are using the critic agent to evaluate the arxiv reader agent, to fully determine whether or not the data extracted, or the relevance to micron, is important or not.  

### How it relates to past projects
In the story of inference time-scaling, I wrote about the LLM-as-a-Judge framework for best-of-n sampling.  I utilized a PRM as an outcome reward model to verify the outcomes of multiple chains of thought, and identify the outcome that fit the criteria best.  Additionally, in Falconeye I utilized LLM-as-a-judge (sort of?) to evaluate whether or not a tool is required for a specific query.  

## Overall Tips
Maintain simplicity in agents design
Prioritize transparency by explicitly showing agent planning steps


