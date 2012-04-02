# Copyright 2012 Tom SF Haines

# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this file except in compliance with the License. You may obtain a copy of the License at

#   http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the License for the specific language governing permissions and limitations under the License.



import numpy



class Goal:
  """Interface that defines the purpose of a decision forest - defines what the tree is optimising, what statistics to store at each node and what is returned to the user as the answer when they provide a novel feature to the forest (i.e. how to combine the statistics)."""
  
  def clone(self):
    """Returns a deep copy of this object."""
    raise NotImplementedError
  
  
  def stats(self, es, index, weights = None):
    """Generates a statistics entity for a node, based on the features that make it to the node. The statistics entity is decided by the task at hand, but must allow the nodes entropy to be calculated, plus a collection of these is used to generate the answer when a feature is given to the decision forest. fs is a feature set, index the indices of the features in fs that have made it to this node. weights is an optional set of weights for the features, weighting how many features they are worth - will be a 1D numpy.float32 array aligned with the feature set, and can contain fractional weights."""
    raise NotImplementedError
  
  def updateStats(self, stats, es, index, weights = None):
    """Given a stats entity, as generated by the stats method, this returns a copy of that stats entity that has had additional exemplars factored in, specifically those passed in. This allows a tree to be updated with further trainning examples (Or, at least its stats to be updated - its structure is set in stone once built.) Needed for incrimental learning."""
    raise NotImplementedError

  def entropy(self, stats):
    """Given a statistics entity this returns the associated entropy - this is used to choose which test is best."""
    raise NotImplementedError
  

  def answer_types(self):
    """When classifying a new feature an answer is to be provided, of which several possibilities exist. This returns a dictionary of those possibilities (key==name, value=human readable description of what it is.), from which the user can select. By convention 'best' must always exist, as the best guess that the algorithm can give (A point estimate of the answer the user is after.). If a probability distribution over 'best' can be provided then that should be avaliable as 'prob' (It is highly recomended that this be provided.)."""
    return {'best':'Point estimate of the best guess at an answer, in the same form that it was provided for the trainning stage.'}
  
  def answer(self, stats_list, which):
    """Given a feature then using a forest a list of statistics entitys can be obtained from the leaf nodes that the feature ends up in, one for each tree (Could be as low as just one entity.). This converts that statistics entity list into an answer, to be passed to the user. As multiple answer types exist (As provided by the answer_types method.) you provide the one(s) you want to the which variable - if which is a string then that answer type is returned, if it is a list of strings then a tuple aligned with it is returned, containing multiple answers. If multiple types are needed then returning a list should hopefuly be optimised by this method to avoid duplicate calculation."""
    raise NotImplementedError
  
  
  def summary(self, es, index, weights = None):
    """Once a tree has been grown a testing set (The 'out-of-bag' set) is typically run through to find out how good it is. This consists of two steps, the first of which is to generate a summary of the oob set that made it to each leaf. This generates the summary, and must be done such that the next step - the use of a stats and summary entity to infer an error metric with a weight for averaging the error metrics from all leafs, can be performed. For incrimental learning it is also required to be able to add new exemplars at a later time."""
    raise NotImplementedError
  
  def updateSummary(self, summary, es, index, weights = None):
    """For incrimental learning the summaries need to be updated with further testing examples - this does that. Given a summary and some exemplars it returns a copy of the summary updated with the new exemplars."""
    raise NotImplementedError
  
  def error(self, stats, summary):
    """Given a stats entity and a summary entity (i.e. the details of the testing and trainning sets that have reached a leaf) this returns the error of the testing set versus the model learnt from the trainning set. The actual return is a pair - (error, weight), so that the errors from all the leafs can be combined in a weighted average. The error metric is arbitary, but the probability of 'being wrong' is a good choice."""
    raise NotImplementedError



class Classification(Goal):
  """The standard goal of a decision forest - classification. When trainning expects the existence of a discrete channel containing a single feature for each exemplar, the index of which is provided. Each discrete feature indicates a different trainning class, and they should be densly packed, starting from 0 inclusive, i.e. belonging to the set {0, ..., # of classes-1}. Number of classes is also provided."""
  def __init__(self, classCount, channel):
    """You provide firstly how many classes exist, and secondly the index of the channel that contains the ground truth for the exemplars. This channel must contain a single integer value, ranging from 0 inclusive to the number of classes, exclusive."""
    self.classCount = classCount
    self.channel = channel
  
  def clone(self):
    return Classification(self.classCount, self.channel)
  
  
  def stats(self, es, index, weights = None):
    if len(index)!=0: 
      ret = numpy.bincount(es[self.channel, index, 0], weights=weights[index] if weights!=None else None)
    else:
      ret = numpy.zeros(self.classCount, dtype=numpy.float32)
    ret = numpy.asarray(ret, dtype=numpy.float32)
    if ret.shape[0]<self.classCount: ret = numpy.concatenate((ret, numpy.zeros(self.classCount-ret.shape[0], dtype=numpy.float32))) # When numpy 1.6.0 becomes common this line can be flipped to a minlength term in the bincount call.
    
    return ret.tostring()
  
  def updateStats(self, stats, es, index, weights = None):
    ret = numpy.fromstring(stats, dtype=numpy.float32)
    toAdd = numpy.bincount(es[self.channel, index, 0], weights=weights[index] if weights!=None else None)
    ret[:toAdd.shape[0]] += toAdd
    
    return ret.tostring()

  def entropy(self, stats):
    dist = numpy.fromstring(stats, dtype=numpy.float32)
    dist = dist[dist>1e-6] / dist.sum()
    return -(dist*numpy.log(dist)).sum() # At the time of coding scipy.stats.distributions.entropy is broken-ish <rolls eyes> (Gives right answer at the expense of filling your screen with warning about zeros.).


  def answer_types(self):
    return {'best':'An integer indexing the class this feature is most likelly to belong to given the model.',
            'prob':'A categorical distribution over class membership, represented as a numpy array of float32 type. Gives the probability of it belonging to each class.'}
  
  def answer(self, stats_list, which):
    # Convert to a list, and process like that, before correcting for the return - simpler...
    single = isinstance(which, str)
    if single: which = [which]
    
    # Calulate the probability distribution over class membership if needed...
    if ('prob' in which) or ('best' in which):
      prob = numpy.zeros(self.classCount, dtype=numpy.float32)
      for stats in stats_list:
        dist = numpy.fromstring(stats, dtype=numpy.float32)
        prob += dist / dist.sum()
      prob /= prob.sum()
    
    # Prepare the return...
    def make_answer(t):
      if t=='prob': return prob
      elif t=='best': return prob.argmax()
    
    ret = map(make_answer, which)
    
    # Make sure the correct thing is returned...
    if single: return ret[0]
    else: return tuple(ret)


  def summary(self, es, index, weights = None):
    ret = numpy.bincount(es[self.channel, index, 0], weights=weights[index] if weights!=None else None)
    ret = numpy.asarray(ret, dtype=numpy.float32)
    if ret.shape[0]<self.classCount: ret = numpy.concatenate((ret, numpy.zeros(self.classCount-ret.shape[0], dtype=numpy.float32))) # When numpy 1.6.0 becomes common this line can be flipped to a minlength term in the bincount call.
    
    return ret.tostring()
  
  def updateSummary(self, summary, es, index, weights = None):
    ret = numpy.fromstring(summary, dtype=numpy.float32)
    toAdd = numpy.bincount(es[self.channel, index,0], weights=weights[index] if weights!=None else None)
    ret[:toAdd.shape[0]] += toAdd
    
    return ret.tostring()
  
  def error(self, stats, summary):
    # Treats the histogram of trainning samples as a probability distribution from which the answer is drawn from - the error is then the average probability of getting each sample in the sample wrong, and the weight the number of exemplars that went into the sample...
    ## Fetch the distribution/counts...
    dist = numpy.fromstring(stats, dtype=numpy.float32)
    dist /= dist.sum()
    test = numpy.fromstring(summary, dtype=numpy.float32)
    count = test.sum()
    
    # Calculate and average the probabilities...
    avgError = ((1.0-dist)*test).sum() / count
    
    return avgError, count